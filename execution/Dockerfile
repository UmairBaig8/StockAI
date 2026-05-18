FROM rust:1.95-slim AS builder

RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY Cargo.toml Cargo.lock ./
COPY src/ ./src/

ENV CARGO_BUILD_JOBS=1
ENV CARGO_NET_RETRY=10

ARG BUILD_MODE=debug
RUN if [ "$BUILD_MODE" = "release" ]; then cargo build --release --bin execution && cp target/release/execution /execution; else cargo build --bin execution && cp target/debug/execution /execution; fi

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /execution /usr/local/bin/execution

CMD ["execution"]
