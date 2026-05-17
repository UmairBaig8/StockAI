use crate::broker::client::BrokerClient;
use crate::broker::types::{Order, OrderSide, OrderStatus, OrderType};
use crate::config::Config;
use crate::orderbook::book::OrderBook;
use rust_decimal::Decimal;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{error, info, warn};

pub struct ExecutionEngine {
    config: Arc<Config>,
    client: BrokerClient,
    active_orders: Arc<RwLock<HashMap<String, Order>>>,
    positions: Arc<RwLock<HashMap<String, Position>>>,
}

#[derive(Debug, Clone)]
pub struct Position {
    pub ticker: String,
    pub quantity: u64,
    pub avg_price: Decimal,
    pub side: OrderSide,
}

#[derive(Debug)]
pub enum Decision {
    Buy {
        ticker: String,
        exchange: String,
        quantity: u64,
        price: Decimal,
        order_type: OrderType,
        reason: String,
    },
    Sell {
        ticker: String,
        exchange: String,
        quantity: u64,
        price: Decimal,
        order_type: OrderType,
        reason: String,
    },
    Hold {
        reason: String,
    },
}

impl ExecutionEngine {
    pub fn new(config: Arc<Config>) -> Self {
        let client = BrokerClient::new(config.clone());
        Self {
            config,
            client,
            active_orders: Arc::new(RwLock::new(HashMap::new())),
            positions: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    pub async fn execute(&self, decision: Decision, _book: &OrderBook) -> Result<Order, String> {
        match decision {
            Decision::Buy {
                ticker,
                exchange,
                quantity,
                price,
                order_type,
                reason,
            } => {
                info!("EXECUTE BUY: {ticker} qty={quantity} price={price} reason={reason}");

                if let Err(e) = self.risk_check(&ticker, quantity, price).await {
                    warn!("Risk check failed for {ticker}: {e}");
                    return Err(format!("Risk check: {e}"));
                }

                let order = Order::new(
                    "stockai-agent",
                    &ticker,
                    &exchange,
                    OrderSide::Buy,
                    order_type,
                    quantity,
                    Some(price),
                    None,
                );

                match self.client.place_order(&order).await {
                    Ok(confirmation) => {
                        if matches!(confirmation.status, OrderStatus::Rejected) {
                            error!("Order {} rejected: {}", order.id, confirmation.message);
                            return Err(confirmation.message);
                        }
                        let mut orders = self.active_orders.write().await;
                        let mut order = order;
                        order.status = confirmation.status;
                        orders.insert(order.id.clone(), order.clone());
                        info!("Order placed: {} {} {} @ {}", order.id, order.ticker, order.side_string(), price);
                        Ok(order)
                    }
                    Err(e) => {
                        error!("Failed to place order: {e}");
                        Err(e)
                    }
                }
            }
            Decision::Sell {
                ticker,
                exchange,
                quantity,
                price,
                order_type,
                reason,
            } => {
                info!("EXECUTE SELL: {ticker} qty={quantity} price={price} reason={reason}");

                let order = Order::new(
                    "stockai-agent",
                    &ticker,
                    &exchange,
                    OrderSide::Sell,
                    order_type,
                    quantity,
                    Some(price),
                    None,
                );

                match self.client.place_order(&order).await {
                    Ok(confirmation) => {
                        if matches!(confirmation.status, OrderStatus::Rejected) {
                            error!("Order {} rejected: {}", order.id, confirmation.message);
                            return Err(confirmation.message);
                        }
                        let mut orders = self.active_orders.write().await;
                        let mut order = order;
                        order.status = confirmation.status;
                        orders.insert(order.id.clone(), order.clone());
                        info!("Order placed: {} {} {} @ {}", order.id, order.ticker, "SELL", price);
                        Ok(order)
                    }
                    Err(e) => {
                        error!("Failed to place order: {e}");
                        Err(e)
                    }
                }
            }
            Decision::Hold { reason } => {
                info!("HOLD: {reason}");
                Err("hold decision — no trade executed".into())
            }
        }
    }

    async fn risk_check(&self, ticker: &str, quantity: u64, price: Decimal) -> Result<(), String> {
        if quantity == 0 {
            return Err("Quantity must be > 0".into());
        }

        let notional = Decimal::from(quantity) * price;

        let positions = self.positions.read().await;
        let existing = positions
            .get(ticker)
            .map(|p| Decimal::from(p.quantity) * p.avg_price)
            .unwrap_or(Decimal::ZERO);

        let total_exposure = existing + notional;

        if total_exposure > Decimal::from_f64_retain(self.config.max_position_pct).unwrap() * Decimal::from(1_000_000)
        {
            return Err(format!(
                "Position size {total_exposure} exceeds max {max_pct}% of capital",
                max_pct = self.config.max_position_pct
            ));
        }

        Ok(())
    }

    pub async fn cancel_order(&self, order_id: &str) -> Result<(), String> {
        match self.client.cancel_order(order_id).await {
            Ok(confirmation) => {
                let mut orders = self.active_orders.write().await;
                if let Some(order) = orders.get_mut(order_id) {
                    order.status = confirmation.status;
                }
                info!("Order {order_id} cancelled");
                Ok(())
            }
            Err(e) => Err(e),
        }
    }

    pub async fn active_order_count(&self) -> usize {
        self.active_orders.read().await.len()
    }
}

impl Order {
    fn side_string(&self) -> &str {
        match self.side {
            OrderSide::Buy => "BUY",
            OrderSide::Sell => "SELL",
        }
    }
}
