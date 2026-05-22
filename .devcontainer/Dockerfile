FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive && apt-get install -y \
    curl wget git build-essential pkg-config libssl-dev cmake \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python 3.12 + uv
RUN curl -sSL https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz | tar xz -C /usr/local/bin --strip-components=1 \
    && chmod +x /usr/local/bin/uv

# Go 1.24
RUN curl -sSL https://go.dev/dl/go1.24.3.linux-amd64.tar.gz | tar -C /usr/local -xzf - \
    && echo 'export PATH=/usr/local/go/bin:$PATH' >> /etc/bash.bashrc

ENV PATH="/usr/local/go/bin:${PATH}"

# Rust (stable)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --component rustfmt clippy \
    && echo 'source $HOME/.cargo/env' >> /etc/bash.bashrc

ENV PATH="/home/vscode/.cargo/bin:${PATH}"

# Docker CLI (for docker-compose)
RUN curl -sSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz | tar xz -C /tmp \
    && cp /tmp/docker/docker /usr/local/bin/docker \
    && chmod +x /usr/local/bin/docker \
    && rm -rf /tmp/docker
