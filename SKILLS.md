# StockAI Skills Guide

> AI agent automation for StockAI development. Skills auto-load based on what you're working on.

## What Are Skills?

Skills are context-aware instruction files that tell the AI assistant how to work with specific parts of the codebase. Each skill contains:
- Architecture diagrams and file maps
- Development commands and workflows
- Key patterns and best practices
- File locations and dependencies

## How They Work

1. You describe what you want to do in natural language
2. The AI detects which skill matches your request
3. The skill loads automatically with all relevant context
4. The AI follows the skill's instructions to complete the task

No manual activation needed — just talk naturally about your task.

## Available Skills

### `aws-ops` — AWS Infrastructure + Git

**Triggers:** "deploy", "update aws", "aws start/stop", "fresh start", "commit and deploy", "check aws"

**What it does:**
- Git commit → push → deploy workflow
- EC2 start/stop via Lambda scheduler
- Data reset (PostgreSQL + Redis + LanceDB wipe)
- Status checks, log viewing, snapshots
- CloudFormation stack management

**Example commands:**
```
"update aws with latest fixes"     → commits, pushes, deploys
"aws status"                       → checks instance + services
"reset data for fresh start"       → wipes all trading data
"view memory logs"                 → tails memory service logs
"take a snapshot"                  → manual EBS snapshot
```

---

### `python-memory` — Python Trading System

**Triggers:** "python", "strategy", "critic", "LLM", "lancedb", "add agent", "fix python bug"

**What it does:**
- FastAPI service development
- Adding new AI agents (Critic, Researcher, etc.)
- LLM provider configuration (DeepSeek, Gemini, OpenAI, Anthropic, Bedrock)
- LanceDB vector store operations
- PostgreSQL schema changes
- API endpoint additions

**Example commands:**
```
"add a new sentiment agent"        → creates agent, wires into pipeline
"change LLM to Gemini"             → updates config, env vars
"add API endpoint for analytics"   → creates route, model, response
"fix strategy signal bug"          → debugs strategy.py, tests fix
```

---

### `rust-engine` — Rust Execution Engine

**Triggers:** "rust", "engine", "broker", "orderbook", "cargo", "fix rust bug"

**What it does:**
- Execution engine development
- Mock broker modifications
- Order book and fill simulation
- Redis pub/sub integration
- WebSocket market data client
- Performance optimization

**Example commands:**
```
"add trailing stop logic"          → modifies engine order logic
"fix order fill slippage"          → debugs mock broker, adds test
"optimize redis connection"        → improves pub/sub performance
"build for production"             → cargo build --release, copies binary
```

---

### `go-orchestrator` — Go Orchestrator

**Triggers:** "go", "orchestrator", "telegram", "2fa", "redis pub/sub", "add alert"

**What it does:**
- Redis pub/sub message handling
- Telegram bot development
- TOTP 2FA flow modifications
- Scheduler job additions
- New alert type creation
- Message handler patterns

**Example commands:**
```
"add weekly report telegram alert" → creates handler, formats message
"fix TOTP validation bug"          → debugs token package, adds test
"add new redis channel"            → creates subscription, handler
"change scheduler timing"          → modifies cron expression
```

---

### `testing` — Test Generation + CI

**Triggers:** "test", "write tests", "pytest", "cargo test", "go test", "coverage", "ci"

**What it does:**
- Generates tests for Python (pytest), Rust (cargo test), Go (go test)
- Table-driven tests for Go, async tests for Python, inline tests for Rust
- CI/CD pipeline setup (GitHub Actions)
- Coverage reporting
- Test pattern examples

**Example commands:**
```
"write tests for strategy"         → generates pytest for strategy.py
"add rust engine tests"            → adds #[cfg(test)] modules
"set up CI pipeline"               → creates .github/workflows/ci.yml
"check test coverage"              → runs coverage, reports gaps
```

---

## Skill Files

All skills live in `.opencode/skills/`:

```
.opencode/skills/
├── aws-ops/SKILL.md          # AWS + Git operations
├── python-memory/SKILL.md    # Python FastAPI service
├── rust-engine/SKILL.md      # Rust execution engine
├── go-orchestrator/SKILL.md  # Go orchestrator + relay
└── testing/SKILL.md          # Test generation + CI
```

## Adding New Skills

To create a new skill:

1. Create directory: `.opencode/skills/my-skill/`
2. Create `SKILL.md` with:
   - Skill name and description
   - Trigger phrases (what activates it)
   - Architecture/file map
   - Commands and workflows
   - Key patterns and examples
3. The AI will auto-detect it based on trigger phrases

## Tips

- **Be specific:** "add RSI test to strategy" loads both `testing` and `python-memory`
- **Combine workflows:** "commit, push, and update aws" runs full deploy pipeline
- **Reference files:** Skills know file locations — just say "fix strategy.py bug"
- **Ask for help:** "what can I do with aws-ops?" lists all available commands
