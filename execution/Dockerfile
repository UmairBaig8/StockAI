FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# Binary must be pre-built: docker run --platform linux/amd64 -v $(pwd):/build -w /build rust:1.95-slim sh -c "apt-get update && apt-get install -y pkg-config libssl-dev && cargo build --bin execution && cp target/debug/execution /build/execution-bin"
COPY execution-bin /usr/local/bin/execution

CMD ["execution"]
