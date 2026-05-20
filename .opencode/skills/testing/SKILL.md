# Testing

Test generation, validation, and CI for Python (FastAPI), Rust (execution), and Go (orchestrator).

## Triggers

- "test", "testing", "write tests", "add tests"
- "pytest", "cargo test", "go test"
- "unit test", "integration test", "e2e test"
- "test coverage", "ci", "ci/cd"
- "run tests", "validate", "check tests"

## Current State

| Language | Framework | Status |
|----------|-----------|--------|
| Python | pytest | **No test files** — `make test-memory` only imports |
| Rust | cargo test | No test modules in source |
| Go | go test | No test files in packages |

## Test Structure

```
tests/                          # Python tests
├── __init__.py
├── test_strategy.py            # StrategyAgent signals, forced trades
├── test_critic.py              # CriticAgent postmortems, rules
├── test_llm.py                 # LLM provider fallback chain
├── test_market_data.py         # yfinance polling, WS broadcasting
├── test_vector_store.py        # LanceDB CRUD, evolution memory
├── test_wallet.py              # Balance, P&L, positions
├── test_router.py              # API endpoints, responses
├── test_news_scraper.py        # RSS parsing, ticker extraction
├── test_sentiment.py           # Sentiment analysis
├── test_researcher.py          # ResearchAgent analysis
├── test_macro.py               # MacroAnalyst context
└── conftest.py                 # Fixtures, test config

execution/src/                  # Rust tests (inline)
├── broker/
│   └── mod.rs                  # #[cfg(test)] mod tests { ... }
├── engine/
│   └── mod.rs                  # #[cfg(test)] mod tests { ... }
├── mock/
│   └── mod.rs                  # #[cfg(test)] mod tests { ... }
└── orderbook/
    └── mod.rs                  # #[cfg(test)] mod tests { ... }

internal/                       # Go tests
├── broker/
│   └── broker_test.go
├── handler/
│   └── handler_test.go
├── telegram/
│   └── telegram_test.go
├── token/
│   └── token_test.go
└── scheduler/
    └── scheduler_test.go
```

## Commands

### Run All Tests

```bash
make test
```

### Python

```bash
# Quick check
make test-memory

# Full test suite
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ -v --cov=app --cov-report=term-missing

# Specific test
uv run pytest tests/test_strategy.py -v
uv run pytest tests/test_strategy.py::test_rsi_signal -v

# Watch mode
uv run pytest-watch tests/
```

### Rust

```bash
# All tests
cd execution && cargo test

# With output
cd execution && cargo test -- --nocapture

# Specific test
cd execution && cargo test test_order_fill

# Integration tests
cd execution && cargo test --test integration

# Benchmarks
cd execution && cargo bench
```

### Go

```bash
# All tests
go test ./...

# Verbose
go test ./... -v

# Specific package
go test ./internal/broker/ -v

# With coverage
go test ./... -coverprofile=coverage.out
go tool cover -html=coverage.out

# Race detector
go test ./... -race
```

### CI (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: stockai
          POSTGRES_PASSWORD: stockai
          POSTGRES_DB: stockai_test
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4

      - name: Python tests
        run: |
          uv sync
          uv run pytest tests/ -v --cov=app

      - name: Rust tests
        run: |
          cd execution
          cargo clippy -- -D warnings
          cargo test

      - name: Go tests
        run: |
          go vet ./...
          go test ./... -race
```

## Test Patterns

### Python (pytest + httpx)

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.strategy import StrategyAgent

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def strategy():
    return StrategyAgent()

def test_health_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_rsi_buy_signal(strategy):
    quote = {"rsi": 25, "price": 1500.0, "ticker": "RELIANCE"}
    signal = strategy.evaluate(quote)
    assert signal.action == "BUY"
    assert signal.reason == "RSI oversold"

@pytest.mark.asyncio
async def test_lancedb_store():
    from app.vector_store import VectorStore
    store = VectorStore("/tmp/test_lancedb")
    await store.store("query", "response", {"context": "test"})
    results = await store.search("query")
    assert len(results) > 0
```

### Rust (inline tests)

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_order_fill_at_market() {
        let order = Order::market("RELIANCE", Side::Buy, 100, 1500.0);
        let fill = simulate_fill(&order, 0.01);
        assert_eq!(fill.price, 1501.5); // 0.1% slippage
    }

    #[tokio::test]
    async fn test_redis_signal_received() {
        let engine = Engine::test_mode().await;
        engine.publish_signal("RELIANCE", Side::Buy).await;
        let result = engine.wait_for_result().await;
        assert_eq!(result.status, "FILLED");
    }
}
```

### Go (table-driven tests)

```go
func TestValidateTOTP(t *testing.T) {
    tests := []struct {
        name     string
        secret   string
        input    string
        expected bool
    }{
        {"valid", "JBSWY3DPEHPK3PXP", "123456", true},
        {"invalid", "JBSWY3DPEHPK3PXP", "000000", false},
        {"empty", "JBSWY3DPEHPK3PXP", "", false},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := token.ValidateTOTP(tt.secret, tt.input)
            if got != tt.expected {
                t.Errorf("got %v, want %v", got, tt.expected)
            }
        })
    }
}
```

## Priority Test Coverage

### Phase 1: Critical Path (write first)

1. `test_strategy.py` — RSI/MACD/BB signal generation
2. `test_router.py` — API endpoint responses
3. `test_wallet.py` — Balance calculations, P&L
4. `execution/src/engine/` — Order execution logic
5. `internal/token/` — TOTP validation

### Phase 2: Core Logic

6. `test_critic.py` — Postmortem generation
7. `test_llm.py` — Provider fallback chain
8. `test_market_data.py` — yfinance polling
9. `execution/src/orderbook/` — Fill simulation
10. `internal/broker/` — Redis pub/sub

### Phase 3: Integrations

11. `test_vector_store.py` — LanceDB operations
12. `test_news_scraper.py` — RSS parsing
13. `test_sentiment.py` — Sentiment analysis
14. `internal/telegram/` — Bot message formatting
15. `internal/handler/` — Message routing

## File Locations

| File | Purpose |
|------|---------|
| `Makefile` | `make test`, `make test-memory`, `make test-go`, `make test-rust` |
| `pyproject.toml` | Python test dependencies (add pytest, pytest-asyncio, httpx) |
| `execution/Cargo.toml` | Rust test config |
| `go.mod` | Go test dependencies |

## Adding pytest Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "httpx>=0.28",
    "respx>=0.21",
]
```

Install: `uv sync --all-extras`
