.PHONY: build-go build-rust build-memory run-memory run-orchestrator run-engine run-mock test clean docker-up docker-down

# === Native Builds ===

build-go:
	go build -o bin/orchestrator ./cmd/orchestrator
	go build -o bin/relay ./cmd/relay

build-rust:
	cd execution && cargo build --release

build-memory:
	uv sync

build: build-go build-rust build-memory

# === Run Locally (requires .env) ===

run-memory:
	uv run uvicorn app.main:app --port 8000 --reload

run-orchestrator:
	go run ./cmd/orchestrator

run-engine:
	cd execution && cargo run --bin execution

run-mock:
	cd execution && cargo run --bin mock-broker

# === Docker ===

docker-up:
	docker compose --env-file .env up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# === Testing ===

test-memory:
	uv run python -c "from app.config import get_settings; from app.models import TradePayload, MarketState, CriticResponse; from app.main import app; print('Python OK')"

test-go:
	go vet ./... && go test ./...

test-rust:
	cd execution && cargo clippy && cargo test

test: test-go test-rust test-memory

# === Clean ===

clean:
	rm -rf bin/
	cd execution && cargo clean
	rm -rf data/
