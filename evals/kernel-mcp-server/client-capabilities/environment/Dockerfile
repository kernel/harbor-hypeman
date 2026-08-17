FROM oven/bun:1.3.3-debian

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
RUN git clone https://github.com/kernel/kernel-mcp-server.git . \
    && git checkout --detach 5914b5ab53c4ecc40ce6eab819ca5cfba74a9a56 \
    && rm -rf .git \
    && bun install --frozen-lockfile
