# Rust Execution Engine

High-performance trading execution: order management, mock broker, WebSocket market feeds, Redis pub/sub.

## Triggers

- "rust", "engine", "execution", "cargo"
- "broker", "mock broker", "order placement"
- "orderbook", "order book", "fill simulation"
- "execution engine", "rust test", "cargo build"
- "fix rust bug", "add rust feature", "clippy"

## Architecture

```
execution/
├── Cargo.toml           # Dependencies, binary targets
├── Dockerfile           # Production build (release)
├── Dockerfile.mock      # Mock broker build
├── src/
│   ├── main.rs          # Entry: execution binary
│   ├── lib.rs           # Library root
│   ├── config.rs        # Config: Redis addr, mock mode, WS URLs
│   ├── bin/
│   │   └── mock_broker.rs  # Mock broker binary (paper trading)
│   ├── broker/          # Broker interface, order management
│   ├── engine/          # Core execution logic
│   ├── market/          # Market data WebSocket client
│   ├── mock/            # Mock broker implementation
│   └── orderbook/       # Order book, fill simulation
└── target/              # Build artifacts (gitignored)
```

## Binaries

| Binary | Source | Purpose |
|--------|--------|---------|
| `execution` | `src/main.rs` | Production execution engine |
| `mock-broker` | `src/bin/mock_broker.rs` | Paper trading simulator |

## Pipeline

```
Redis trade:signal
    ↓
Engine receives signal
    ↓
Order validation (SEBI rate limits, position checks)
    ↓
Mock broker: simulate fill with slippage
    ↓
Publish trade:result to Redis
    ↓
Strategy listens, tracks P&L
```

## Commands

### Build

```bash
# Debug (fast)
cd execution && cargo build

# Release (production)
cd execution && cargo build --release

# Output binary
cp execution/target/release/execution execution/execution-bin
```

### Run

```bash
# Production engine
cd execution && cargo run --bin execution

# Mock broker (paper trading)
cd execution && cargo run --bin mock-broker
```

### Test

```bash
cd execution && cargo test
cd execution && cargo test -- --nocapture  # with output
cd execution && cargo test <test_name>     # specific test
```

### Lint

```bash
cd execution && cargo clippy
cd execution && cargo clippy -- -D warnings  # fail on warnings
cd execution && cargo fmt -- --check         # format check
cd execution && cargo fmt                    # format fix
```

### Docker

```bash
# Production
docker build -f execution/Dockerfile -t stockai-engine ./execution

# Mock
docker build -f execution/Dockerfile.mock -t stockai-mock ./execution
```

### Makefile

```bash
make build-rust      # cargo build --release
make run-engine      # cargo run --bin execution
make run-mock        # cargo run --bin mock-broker
make test-rust       # cargo clippy && cargo test
```

## Key Patterns

### Adding a New Broker

1. Implement `Broker` trait in `execution/src/broker/`
2. Add config fields in `config.rs`
3. Wire into engine initialization
4. Add feature flag in `Cargo.toml` if optional

### Adding Order Type

1. Add variant to `OrderType` enum in `orderbook/`
2. Implement fill logic in `orderbook/fill.rs`
3. Add validation in `broker/validate.rs`
4. Update mock broker simulation

### Redis Integration

```rust
// Subscribe to trade:signal
let mut sub = redis_client.subscribe(&["trade:signal"]).await?;
while let Some(msg) = sub.next_message().await? {
    let signal: TradeSignal = serde_json::from_str(&msg.payload)?;
    // Execute...
    // Publish result
    redis_client.publish("trade:result", &result).await?;
}
```

### WebSocket Market Data

```rust
// Connect to Memory service WS feed
let (ws, _) = connect(&market_ws_url).await?;
while let Some(msg) = ws.next().await {
    let quote: Quote = parse_quote(msg)?;
    // Update orderbook, check triggers
}
```

## Dependencies

```
tokio (async runtime)
axum (HTTP/WS server)
serde, serde_json (serialization)
tokio-tungstenite (WS client)
redis (pub/sub)
reqwest (HTTP client)
tracing, tracing-subscriber (logging)
uuid, chrono, rust_decimal, fastrand
```

## File Locations

| File | Purpose |
|------|---------|
| `execution/src/main.rs` | Production engine entry |
| `execution/src/bin/mock_broker.rs` | Mock broker entry |
| `execution/src/broker/` | Broker interface |
| `execution/src/engine/` | Core execution logic |
| `execution/src/market/` | Market data WS client |
| `execution/src/mock/` | Mock broker implementation |
| `execution/src/orderbook/` | Order book, fill simulation |
| `execution/src/config.rs` | Configuration |
| `execution/Cargo.toml` | Dependencies |
| `execution/Dockerfile` | Production Docker |

## SEBI Compliance

- Rate limiting: max orders per minute
- Position limits: max position size
- Audit trail: all orders logged
- Paper mode: `MOCK_MODE=true` bypasses real execution
