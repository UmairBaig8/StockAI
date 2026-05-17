use crate::broker::types::*;
use crate::config::Config;
use futures_util::StreamExt;
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

pub struct BrokerClient {
    config: Arc<Config>,
    http_client: reqwest::Client,
}

impl BrokerClient {
    pub fn new(config: Arc<Config>) -> Self {
        Self {
            config,
            http_client: reqwest::Client::new(),
        }
    }

    pub async fn place_order(&self, order: &Order) -> Result<OrderConfirmation, String> {
        let url = format!("{}/orders", self.config.broker_rest_url);
        let payload = serde_json::to_value(order).map_err(|e| e.to_string())?;

        let resp = self
            .http_client
            .post(&url)
            .header("X-API-Key", &self.config.api_key)
            .header("X-API-Secret", &self.config.api_secret)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {e}"))?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            return Err(format!("Broker error {status}: {body}"));
        }

        let confirmation: OrderConfirmation =
            resp.json().await.map_err(|e| format!("JSON error: {e}"))?;
        Ok(confirmation)
    }

    pub async fn cancel_order(&self, order_id: &str) -> Result<OrderConfirmation, String> {
        let url = format!("{}/orders/{}", self.config.broker_rest_url, order_id);
        let resp = self
            .http_client
            .delete(&url)
            .header("X-API-Key", &self.config.api_key)
            .header("X-API-Secret", &self.config.api_secret)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {e}"))?;

        let confirmation: OrderConfirmation =
            resp.json().await.map_err(|e| format!("JSON error: {e}"))?;
        Ok(confirmation)
    }

    pub async fn connect_feed(
        &self,
        _tickers: &[String],
        quote_tx: mpsc::Sender<Quote>,
    ) -> Result<(), String> {
        let ws_url = self.config.broker_ws_url.clone();

        info!("Connecting to market feed: {}", ws_url);

        let (ws_stream, _) = tokio_tungstenite::connect_async(&ws_url)
            .await
            .map_err(|e| format!("WebSocket connect error: {e}"))?;

        info!("Market feed connected");

        let (_, mut read) = ws_stream.split();

        while let Some(msg) = read.next().await {
            match msg {
                Ok(tokio_tungstenite::tungstenite::Message::Text(text)) => {
                    match serde_json::from_str::<WebsocketMessage>(&text) {
                        Ok(ws_msg) if ws_msg.msg_type == "quote" => {
                            match serde_json::from_value::<Quote>(ws_msg.data) {
                                Ok(quote) => {
                                    if quote_tx.send(quote).await.is_err() {
                                        warn!("Quote channel closed, disconnecting feed");
                                        break;
                                    }
                                }
                                Err(e) => {
                                    warn!("Failed to parse quote: {e}");
                                }
                            }
                        }
                        Ok(ws_msg) => {
                            info!("Received message type: {}", ws_msg.msg_type);
                        }
                        Err(e) => {
                            warn!("Failed to parse WebSocket message: {e}");
                        }
                    }
                }
                Ok(tokio_tungstenite::tungstenite::Message::Close(_)) => {
                    info!("Market feed connection closed by server");
                    break;
                }
                Ok(other) => {
                    info!("Received non-text message: {:?}", other);
                }
                Err(e) => {
                    error!("WebSocket error: {e}");
                    break;
                }
            }
        }

        Ok(())
    }
}
