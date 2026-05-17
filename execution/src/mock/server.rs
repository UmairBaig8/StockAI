use axum::extract::{Path, State, WebSocketUpgrade};
use axum::extract::ws::{Message, WebSocket};
use axum::response::IntoResponse;
use axum::{Json, Router};
use crate::broker::types::*;
use rust_decimal::Decimal;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;
use tracing::info;

pub struct MockBrokerState {
    pub orders: RwLock<HashMap<String, Order>>,
}

pub async fn run_mock_broker(port: u16) {
    let state = Arc::new(MockBrokerState {
        orders: RwLock::new(HashMap::new()),
    });

    let app = Router::new()
        .route("/orders", axum::routing::post(place_order))
        .route("/orders/{id}", axum::routing::delete(cancel_order))
        .route("/ws", axum::routing::get(ws_handler))
        .with_state(state);

    let addr = format!("0.0.0.0:{port}");
    info!("Mock broker listening on {addr}");
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .expect("Failed to bind mock broker");
    axum::serve(listener, app).await.unwrap();
}

async fn place_order(
    State(state): State<Arc<MockBrokerState>>,
    Json(mut order): Json<Order>,
) -> impl IntoResponse {
    order.status = OrderStatus::Open;
    let confirmation = OrderConfirmation {
        order_id: order.id.clone(),
        status: OrderStatus::Open,
        message: "Order accepted".into(),
    };

    let mut orders = state.orders.write().await;
    orders.insert(order.id.clone(), order);
    info!("Mock: Order placed {}", confirmation.order_id);

    Json(confirmation)
}

async fn cancel_order(
    State(state): State<Arc<MockBrokerState>>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    let mut orders = state.orders.write().await;
    if let Some(order) = orders.get_mut(&id) {
        order.status = OrderStatus::Cancelled;
    }

    let confirmation = OrderConfirmation {
        order_id: id,
        status: OrderStatus::Cancelled,
        message: "Order cancelled".into(),
    };
    info!("Mock: Order cancelled {}", confirmation.order_id);
    Json(confirmation)
}

async fn ws_handler(
    State(state): State<Arc<MockBrokerState>>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_ws(socket, state))
}

async fn handle_ws(mut socket: WebSocket, _state: Arc<MockBrokerState>) {
    info!("Mock: WebSocket client connected");

    let tickers = vec![
        ("RELIANCE", Decimal::new(2900, 0), Decimal::new(2905, 0)),
        ("TATAPOWER", Decimal::new(430, 0), Decimal::new(432, 0)),
        ("HAL", Decimal::new(5100, 0), Decimal::new(5105, 0)),
        ("BEL", Decimal::new(310, 0), Decimal::new(312, 0)),
    ];

    let mut interval = tokio::time::interval(Duration::from_millis(500));

    loop {
        interval.tick().await;

        for (ticker, base_bid, base_ask) in &tickers {
            let jitter = fastrand::i32(-50..50);
            let bid = base_bid + Decimal::from(jitter);
            let ask = base_ask + Decimal::from(jitter) + Decimal::from(2);

            let quote = Quote {
                ticker: ticker.to_string(),
                exchange: "NSE".into(),
                bid,
                ask,
                bid_qty: fastrand::u64(100..10000),
                ask_qty: fastrand::u64(100..10000),
                last_price: (bid + ask) / Decimal::from(2),
                volume: fastrand::u64(1000..50000),
                timestamp: chrono::Utc::now(),
            };

            let ws_msg = WebsocketMessage {
                msg_type: "quote".into(),
                data: serde_json::to_value(&quote).unwrap(),
            };

            let json = serde_json::to_string(&ws_msg).unwrap();
            if socket.send(Message::Text(json.into())).await.is_err() {
                info!("Mock: WebSocket client disconnected");
                return;
            }
        }
    }
}
