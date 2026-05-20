# Go Orchestrator

Redis pub/sub message broker, Telegram 2FA relay, scheduler for trading pipeline.

## Triggers

- "go", "golang", "orchestrator", "relay"
- "telegram", "2fa", "totp", "bot"
- "redis pub/sub", "scheduler", "cron"
- "fix go bug", "add go feature", "go test"
- "telegram alert", "trade notification"

## Architecture

```
cmd/
├── orchestrator/        # Main orchestrator binary
│   └── main.go
└── relay/               # TOTP 2FA relay server
    └── main.go

internal/
├── broker/              # Redis pub/sub handler
├── config/              # Configuration loading
├── handler/             # Message handlers
├── scheduler/           # Cron-like job scheduler
├── telegram/            # Telegram bot integration
└── token/               # TOTP token generation/validation

go.mod
go.sum
Dockerfile.orchestrator
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| Orchestrator | 8080 | HTTP server, TOTP relay, health check |
| Relay | — | Telegram 2FA code forwarding |

## Pipeline

```
Strategy → Redis trade:signal
    ↓
Orchestrator receives signal
    ↓
If MOCK_MODE: bypass 2FA
If live: request TOTP from user via Telegram
    ↓
TOTP validated → forward to Engine
    ↓
Engine executes → result back to Strategy
```

## Telegram Alerts

| Event | Trigger | Content |
|-------|---------|---------|
| BUY | Trade opened | Direction, price, quantity, reason |
| SELL | Trade closed | P&L, hold duration |
| Postmortem | Loss detected | What went wrong, correction rule |
| Daily Report | 15:30 IST | Total trades, win rate, net P&L |

## Commands

### Build

```bash
# All Go binaries
make build-go

# Individual
go build -o bin/orchestrator ./cmd/orchestrator
go build -o bin/relay ./cmd/relay
```

### Run

```bash
# Orchestrator
go run ./cmd/orchestrator

# Relay
go run ./cmd/relay
```

### Test

```bash
go vet ./...
go test ./...
go test ./... -v          # verbose
go test ./internal/...    # specific package
```

### Lint

```bash
go vet ./...
golangci-lint run         # if installed
```

### Docker

```bash
docker build -f Dockerfile.orchestrator -t stockai-orchestrator .
```

### Makefile

```bash
make build-go        # build orchestrator + relay
make run-orchestrator  # go run ./cmd/orchestrator
make test-go         # go vet && go test
```

## Key Patterns

### Adding a New Handler

1. Create handler in `internal/handler/new_handler.go`
2. Register in broker subscription in `internal/broker/`
3. Add message type to handler interface
4. Wire in `cmd/orchestrator/main.go`

### Adding Telegram Alert Type

1. Add method to `internal/telegram/bot.go`
2. Call from handler on event trigger
3. Format message with emoji indicators
4. Test with `TELEGRAM_CHAT_ID` in `.env`

### Redis Pub/Sub

```go
// Subscribe to channel
pubsub := rdb.Subscribe(ctx, "trade:signal")
ch := pubsub.Channel()
for msg := range ch {
    var signal TradeSignal
    json.Unmarshal([]byte(msg.Payload), &signal)
    // Handle...
}

// Publish
rdb.Publish(ctx, "trade:result", result)
```

### TOTP 2FA Flow

```go
// Generate TOTP
code := token.GenerateTOTP(secret)

// Validate user input
valid := token.ValidateTOTP(secret, userInput)

// If MOCK_MODE, skip validation
if config.MockMode {
    return true
}
```

## Configuration

```env
TELEGRAM_BOT_TOKEN=8906698066:AAGoobut4YESEP4kwZ5kteYzKW73QSFOY2Ww
TELEGRAM_CHAT_ID=7775593886
RELAY_URL=http://localhost:8080
REDIS_ADDR=redis:6379
MEMORY_URL=http://memory:8000
HTTP_PORT=8080
```

## File Locations

| File | Purpose |
|------|---------|
| `cmd/orchestrator/main.go` | Orchestrator entry |
| `cmd/relay/main.go` | TOTP relay entry |
| `internal/broker/` | Redis pub/sub |
| `internal/handler/` | Message handlers |
| `internal/scheduler/` | Cron jobs |
| `internal/telegram/` | Telegram bot |
| `internal/token/` | TOTP generation |
| `internal/config/` | Configuration |
| `go.mod` | Go dependencies |
| `Dockerfile.orchestrator` | Docker build |

## Dependencies

```
github.com/redis/go-redis/v9
github.com/cespare/xxhash/v2
go.uber.org/atomic
```
