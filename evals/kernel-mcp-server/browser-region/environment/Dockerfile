FROM oven/bun:1.3.3-debian

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
RUN git clone https://github.com/kernel/kernel-mcp-server.git . \
    && git checkout --detach 2d98491389b6a129fec797e0f35c6b5e4ab9d695 \
    && rm -rf .git \
    && bun install --frozen-lockfile
