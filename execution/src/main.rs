use std::sync::Arc;
use std::collections::HashMap;
use std::env;
use std::time::Instant;
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
    reason: String,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    suspect: bool,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct OpenPosition {
    qty: u64,
    entry_price: f64,
}

/// Token bucket rate limiter — SEBI <10 orders/sec
struct RateLimiter {
    tokens: f64,
    max_tokens: f64,
    refill_rate: f64, // tokens per second
    last_refill: Instant,
}

impl RateLimiter {
    fn new(max_tokens: u32, refill_per_sec: f64) -> Self {
        Self {
            tokens: max_tokens as f64,
            max_tokens: max_tokens as f64,
            refill_rate: refill_per_sec,
            last_refill: Instant::now(),
        }
    }

    fn try_acquire(&mut self) -> bool {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_refill).as_secs_f64();
        self.tokens = (self.tokens + elapsed * self.refill_rate).min(self.max_tokens);
        self.last_refill = now;
        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            true
        } else {
            false
        }
    }
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
        if let Err(e) = signal_loop(engine_redis, sig_prices, &mut redis_pubsub, &mut redis_pub, config.mock_mode).await {
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
    _price_map: PriceMap,
    pubsub: &mut PubSub,
    pub_conn: &mut MultiplexedConnection,
    mock_mode: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    pubsub.subscribe("trade:signal").await?;
    info!("Subscribed to trade:signal");

    let mut positions: HashMap<String, OpenPosition> = HashMap::new();
    let mut rate_limiter = RateLimiter::new(10, 1.0); // 10 burst, refill 1/sec

    // Restore positions from Redis (survive engine restarts)
    let redis_persist = redis::Client::open(redis_addr()).ok();
    if let Some(ref rp) = redis_persist {
        if let Ok(mut conn) = rp.get_multiplexed_async_connection().await {
            let stored: HashMap<String, String> = redis::cmd("HGETALL")
                .arg("engine:positions")
                .query_async(&mut conn)
                .await
                .unwrap_or_default();
            for (ticker, json) in &stored {
                if let Ok(pos) = serde_json::from_str::<OpenPosition>(json) {
                    info!("Restored position from Redis: {} qty={} @ {:.2}", ticker, pos.qty, pos.entry_price);
                    positions.insert(ticker.clone(), pos);
                }
            }
            if !stored.is_empty() {
                info!("Loaded {} positions from Redis", stored.len());
            }
        }
    }

    // Separate Redis client for 2FA check
    let redis_2fa = redis::Client::open(redis_addr()).ok();

    let mut stream = pubsub.on_message();

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

        // SEBI: check 2FA is active before allowing execution (skip in paper/mock mode)
        if !mock_mode {
            if let Some(ref r2fa) = redis_2fa {
                if let Ok(mut conn) = r2fa.get_multiplexed_async_connection().await {
                    let active: Option<String> = redis::cmd("GET").arg("2fa:active").query_async(&mut conn).await.ok().flatten();
                    if active.is_none() {
                        warn!("SEBI 2FA not active — rejecting {} signal for {}", signal.direction, signal.ticker);
                        continue;
                    }
                }
            }
        }

        // SEBI: rate limit (<10 orders/sec)
        if !rate_limiter.try_acquire() {
            warn!("Rate limit exceeded — rejecting {} signal for {}", signal.direction, signal.ticker);
            continue;
        }

        match engine.execute(decision, &Default::default()).await {
            Ok(order) => {
                info!("Order placed: {} {} ({})", order.id, signal.ticker, signal.direction);

                let now = chrono::Utc::now().to_rfc3339();
                let ticker = signal.ticker.clone();

                if signal.direction.to_uppercase() == "BUY" || signal.direction.to_uppercase() == "LONG" {
                    // Open position — publish OPEN status, no P&L yet
                    let op = OpenPosition {
                        qty: signal.quantity,
                        entry_price: signal.price,
                    };

                    // Persist to Redis for crash recovery (serialize before move)
                    let op_json = serde_json::to_string(&op).ok();
                    positions.insert(ticker.clone(), op);

                    if let Some(ref rp) = redis_persist {
                        if let Some(ref json) = op_json {
                            if let Ok(mut conn) = rp.get_multiplexed_async_connection().await {
                                let _: () = redis::cmd("HSET")
                                    .arg("engine:positions")
                                    .arg(&ticker)
                                    .arg(json)
                                    .query_async(&mut conn)
                                    .await
                                    .unwrap_or(());
                            }
                        }
                    }

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
                        reason: signal.reason.clone(),
                        suspect: false,
                    };
                    let result_json = serde_json::to_string(&result).unwrap();
                    let _: () = pub_conn.publish("trade:result", result_json).await?;

                } else {
                    // SELL — compute real P&L using signal price (from yfinance) as exit
                    let pos = positions.remove(&ticker);
                    let exit_price = signal.price;  // strategy sends current yfinance price

                    // Remove from Redis persistence
                    if let Some(ref rp) = redis_persist {
                        if let Ok(mut conn) = rp.get_multiplexed_async_connection().await {
                            let _: () = redis::cmd("HDEL")
                                .arg("engine:positions")
                                .arg(&ticker)
                                .query_async(&mut conn)
                                .await
                                .unwrap_or(());
                        }
                    }

                    let (entry_price, pnl_pct, status, should_publish, suspect) = if let Some(pos) = pos {
                        let pnl = (exit_price - pos.entry_price) / pos.entry_price * 100.0;
                        let s = if pnl >= 0.0 { "WIN" } else { "LOSS" };
                        // Flag suspect trades where entry ≈ exit (possible stale price)
                        let delta = (exit_price - pos.entry_price).abs() / pos.entry_price;
                        let susp = delta < 0.001;
                        if susp {
                            warn!("Suspect trade: {} entry={:.2} exit={:.2} delta={:.4}% — possible stale price", ticker, pos.entry_price, exit_price, delta * 100.0);
                        }
                        info!("Position closed: {} entry={:.2} exit={:.2} pnl={:+.2}% (remaining: {})", ticker, pos.entry_price, exit_price, pnl, positions.len());
                        (pos.entry_price, pnl, s.to_string(), true, susp)
                    } else {
                        // No open position tracked — reject orphaned sell, don't publish bogus result
                        warn!("No open position for {} — rejecting orphaned SELL signal", ticker);
                        (signal.price, 0.0, "REJECTED".to_string(), false, false)
                    };

                    if should_publish {
                        let result = TradeResult {
                            order_id: order.id.clone(),
                            ticker,
                            direction: "SELL".into(),
                            entry_price,
                            exit_price: (exit_price * 100.0).round() / 100.0,
                            quantity: signal.quantity,
                            pnl_percent: (pnl_pct * 100.0).round() / 100.0,
                            status,
                            timestamp: now,
                            reason: signal.reason.clone(),
                            suspect,
                        };
                        let result_json = serde_json::to_string(&result).unwrap();
                        let _: () = pub_conn.publish("trade:result", result_json).await?;
                    }
                }
            }
            Err(e) => {
                warn!("Order rejected: {e}");
            }
        }
    }
}
