use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum OrderSide {
    Buy,
    Sell,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum OrderType {
    Market,
    Limit,
    #[serde(rename = "SL")]
    StopLoss,
    #[serde(rename = "SL-M")]
    StopLossMarket,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum OrderStatus {
    Pending,
    Open,
    Executed,
    Cancelled,
    Rejected,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: String,
    pub trader_id: String,
    pub ticker: String,
    pub exchange: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub quantity: u64,
    pub price: Option<Decimal>,
    pub trigger_price: Option<Decimal>,
    pub status: OrderStatus,
    pub filled_qty: u64,
    pub avg_price: Option<Decimal>,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

impl Order {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        trader_id: &str,
        ticker: &str,
        exchange: &str,
        side: OrderSide,
        order_type: OrderType,
        quantity: u64,
        price: Option<Decimal>,
        trigger_price: Option<Decimal>,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            trader_id: trader_id.into(),
            ticker: ticker.into(),
            exchange: exchange.into(),
            side,
            order_type,
            quantity,
            price,
            trigger_price,
            status: OrderStatus::Pending,
            filled_qty: 0,
            avg_price: None,
            timestamp: chrono::Utc::now(),
        }
    }

    pub fn is_complete(&self) -> bool {
        matches!(self.status, OrderStatus::Executed | OrderStatus::Cancelled | OrderStatus::Rejected)
    }

    pub fn is_active(&self) -> bool {
        matches!(self.status, OrderStatus::Pending | OrderStatus::Open)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Quote {
    pub ticker: String,
    pub exchange: String,
    pub bid: Decimal,
    pub ask: Decimal,
    pub bid_qty: u64,
    pub ask_qty: u64,
    pub last_price: Decimal,
    pub volume: u64,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trade {
    pub id: String,
    pub order_id: String,
    pub ticker: String,
    pub exchange: String,
    pub side: OrderSide,
    pub price: Decimal,
    pub quantity: u64,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderConfirmation {
    pub order_id: String,
    pub status: OrderStatus,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WebsocketMessage {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub data: serde_json::Value,
}
