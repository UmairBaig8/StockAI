use std::sync::Arc;
use std::collections::HashMap;
use std::env;
use tokio::sync::{mpsc, RwLock};
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;

use stockai_execution::broker::client::BrokerClient;
use stockai_execution::broker::types::OrderType;
use stockai_execution::config::Config;
use stockai_execution::engine::execution::{Decision, ExecutionEngine};
use stockai_execution::market::feed::{MarketFeed, PriceMap};

use redis::aio::{MultiplexedConnection, PubSub};
use redis::AsyncCommands;
use futures_util::StreamExt;
use axum::{routing::get, Json, Router};
use std::net::SocketAddr;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct TradeSignal {
    ticker: String,
    exchange: String,
    direction: String,
    quantity: u64,
    price: f64,
    reason: String,
    #[allow(dead_code)]
    timestamp: String,
}

#[derive(Debug, serde::Serialize)]
struct TradeResult {
    order_id: String,
    ticker: String,
    direction: String,
    entry_price: f64,
    exit_price: f64,
    quantity: u64,
    pnl_percent: f64,
    status: String,
    timestamp: String,
}

struct OpenPosition {
    qty: u64,
    entry_price: f64,
}

fn redis_addr() -> String {
    env::var("REDIS_ADDR").unwrap_or_else(|_| "redis://127.0.0.1:6379".into())
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .init();

    info!("StockAI Execution Engine v0.2.0");

    let config = Arc::new(Config::from_env().expect("Failed to load config"));
    let engine = Arc::new(ExecutionEngine::new(config.clone()));

    let (quote_tx, quote_rx) = mpsc::channel(1024);
    let client = BrokerClient::new(config.clone());
    let tickers = vec![
        "RELIANCE".to_string(),
        "TATAPOWER".to_string(),
        "HAL".to_string(),
        "BEL".to_string(),
    ];

    let feed_handle = tokio::spawn(async move {
        if let Err(e) = client.connect_feed(&tickers, quote_tx).await {
            error!("Market feed error: {e}");
        }
    });

    // Shared price map — updated by feed, read by signal_loop
    let price_map: PriceMap = Arc::new(RwLock::new(HashMap::new()));

    let mut market_feed = MarketFeed::with_prices(quote_rx, price_map.clone());
    let feed_proc = tokio::spawn(async move {
        market_feed.run().await;
    });

    let redis_client = redis::Client::open(redis_addr()).expect("Invalid Redis URL");
    let mut redis_pubsub = redis_client.get_async_pubsub().await.expect("Failed to get pubsub");
    let mut redis_pub = redis_client
        .get_multiplexed_async_connection()
        .await
        .expect("Failed to connect to Redis");
    info!("Redis connected");

    let engine_redis = engine.clone();
    let sig_prices = price_map.clone();
    let signal_handle = tokio::spawn(async move {
        if let Err(e) = signal_loop(engine_redis, sig_prices, &mut redis_pubsub, &mut redis_pub).await {
            error!("Signal loop error: {e}");
        }
    });

    // Tiny health HTTP server on port 9001
    let health_handle = tokio::spawn(async move {
        let app = Router::new().route("/health", get(|| async { Json(serde_json::json!({"status":"ok"})) }));
        let addr = SocketAddr::from(([0, 0, 0, 0], 9001));
        info!("Health server on port 9001");
        let listener = tokio::net::TcpListener::bind(addr).await.expect("bind health port");
        axum::serve(listener, app).await.ok();
    });

    info!("Execution engine ready. Awaiting trade signals on trade:signal...");

    tokio::signal::ctrl_c().await.ok();
    info!("Shutting down...");

    feed_handle.abort();
    feed_proc.abort();
    signal_handle.abort();
    health_handle.abort();
}

async fn signal_loop(
    engine: Arc<ExecutionEngine>,
    price_map: PriceMap,
    pubsub: &mut PubSub,
    pub_conn: &mut MultiplexedConnection,
) -> Result<(), Box<dyn std::error::Error>> {
    pubsub.subscribe("trade:signal").await?;
    info!("Subscribed to trade:signal");

    let mut stream = pubsub.on_message();
    let mut positions: HashMap<String, OpenPosition> = HashMap::new();

    loop {
        let msg = stream.next().await.ok_or("pubsub stream ended")?;
        let payload: String = msg.get_payload()?;

        let signal: TradeSignal = match serde_json::from_str(&payload) {
            Ok(s) => s,
            Err(e) => {
                warn!("Invalid trade signal: {e}");
                continue;
            }
        };

        info!("Received signal: {} {} qty={} @ {:.2}", signal.direction, signal.ticker, signal.quantity, signal.price);

        let price = rust_decimal::Decimal::from_f64_retain(signal.price)
            .unwrap_or_default();

        let decision = match signal.direction.to_uppercase().as_str() {
            "BUY" | "LONG" => Decision::Buy {
                ticker: signal.ticker.clone(),
                exchange: signal.exchange.clone(),
                quantity: signal.quantity,
                price,
                order_type: OrderType::Limit,
                reason: signal.reason.clone(),
            },
            "SELL" | "SHORT" => Decision::Sell {
                ticker: signal.ticker.clone(),
                exchange: signal.exchange.clone(),
                quantity: signal.quantity,
                price,
                order_type: OrderType::Limit,
                reason: signal.reason.clone(),
            },
            _ => {
                warn!("Unknown direction: {}", signal.direction);
                continue;
            }
        };

        match engine.execute(decision, &Default::default()).await {
            Ok(order) => {
                info!("Order placed: {} {} ({})", order.id, signal.ticker, signal.direction);

                let now = chrono::Utc::now().to_rfc3339();
                let ticker = signal.ticker.clone();

                if signal.direction.to_uppercase() == "BUY" || signal.direction.to_uppercase() == "LONG" {
                    // Open position — publish OPEN status, no P&L yet
                    positions.insert(ticker.clone(), OpenPosition {
                        qty: signal.quantity,
                        entry_price: signal.price,
                    });
                    info!("Position opened: {} qty={} @ {:.2} (total positions: {})", ticker, signal.quantity, signal.price, positions.len());

                    let result = TradeResult {
                        order_id: order.id.clone(),
                        ticker: ticker,
                        direction: "BUY".into(),
                        entry_price: signal.price,
                        exit_price: signal.price,
                        quantity: signal.quantity,
                        pnl_percent: 0.0,
                        status: "OPEN".into(),
                        timestamp: now,
                    };
                    let result_json = serde_json::to_string(&result).unwrap();
                    let _: () = pub_conn.publish("trade:result", result_json).await?;

                } else {
                    // SELL — compute real P&L from live market price vs entry
                    let pos = positions.remove(&ticker);
                    let exit_price = {
                        let prices = price_map.read().await;
                        prices.get(&ticker).copied().unwrap_or(signal.price)
                    };

                    let (pnl_pct, status) = if let Some(pos) = pos {
                        let pnl = (exit_price - pos.entry_price) / pos.entry_price * 100.0;
                        let s = if pnl >= 0.0 { "WIN" } else { "LOSS" };
                        info!("Position closed: {} entry={:.2} exit={:.2} pnl={:+.2}% (remaining: {})", ticker, pos.entry_price, exit_price, pnl, positions.len());
                        (pnl, s)
                    } else {
                        // No open position tracked — use signal price as reference
                        let pnl = (exit_price - signal.price) / signal.price * 100.0;
                        let s = if pnl >= 0.0 { "WIN" } else { "LOSS" };
                        warn!("No open position for {} — using signal price as entry", ticker);
                        (pnl, s)
                    };

                    let result = TradeResult {
                        order_id: order.id.clone(),
                        ticker,
                        direction: "SELL".into(),
                        entry_price: signal.price,
                        exit_price: (exit_price * 100.0).round() / 100.0,
                        quantity: signal.quantity,
                        pnl_percent: (pnl_pct * 100.0).round() / 100.0,
                        status: status.to_string(),
                        timestamp: now,
                    };
                    let result_json = serde_json::to_string(&result).unwrap();
                    let _: () = pub_conn.publish("trade:result", result_json).await?;
                }
            }
            Err(e) => {
                warn!("Order rejected: {e}");
            }
        }
    }
}
