use std::env;

pub struct Config {
    pub broker_ws_url: String,
    pub broker_rest_url: String,
    pub api_key: String,
    pub api_secret: String,
    pub max_position_pct: f64,
    pub max_loss_per_trade_pct: f64,
    pub max_orders_per_second: u32,
    pub mock_mode: bool,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        Ok(Self {
            broker_ws_url: env::var("BROKER_WS_URL")
                .unwrap_or_else(|_| "ws://127.0.0.1:9001/ws".into()),
            broker_rest_url: env::var("BROKER_REST_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:9001".into()),
            api_key: env::var("BROKER_API_KEY").unwrap_or_default(),
            api_secret: env::var("BROKER_API_SECRET").unwrap_or_default(),
            max_position_pct: env_var_or("MAX_POSITION_PCT", 5.0),
            max_loss_per_trade_pct: env_var_or("MAX_LOSS_PER_TRADE_PCT", 2.0),
            max_orders_per_second: env_var_or("MAX_OPS", 10),
            mock_mode: env::var("MOCK_MODE")
                .map(|v| v == "1" || v == "true")
                .unwrap_or(true),
        })
    }
}

fn env_var_or<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}
