# harbor-hypeman

Run [Harbor Framework](https://github.com/harbor-framework/harbor) evaluations in [Hypeman](https://github.com/kernel/hypeman) sandboxes.

## Install

```bash
uv tool install harbor --with harbor-hypeman
```

Set the Hypeman credentials used by the generated Python SDK:

```bash
export HYPEMAN_API_KEY=...
export HYPEMAN_BASE_URL=https://hypeman.example.com
```

`HYPEMAN_BASE_URL` is optional when Hypeman is available at the SDK default, `http://localhost:4973`.

## Run

Pass the third-party environment import path to Harbor:

```bash
harbor run \
  --dataset terminal-bench@2.0 \
  --agent codex \
  --model openai/gpt-5.6 \
  --env harbor_hypeman:HypemanEnvironment
```

The backend supports task environments defined by either:

- `[environment].docker_image` in `task.toml`
- `environment/Dockerfile`

CPU, memory, and storage values map to Hypeman vCPUs, base memory, and writable overlay size. Harbor `public` and `no-network` modes map to attached and detached Hypeman networking.

## Braintrust reporting

Install the official Braintrust integration with the backend:

```bash
uv tool install harbor \
  --with harbor-hypeman \
  --with 'braintrust>=0.33.0'
```

Then add the official Harbor plugin to a run:

```bash
harbor run \
  --dataset ./tasks \
  --agent codex \
  --model openai/gpt-5.6 \
  --env harbor_hypeman:HypemanEnvironment \
  --plugin braintrust
```

Set the Braintrust credentials required by your project before running the command.

This repository includes two pinned `kernel-mcp-server` tasks for reproducible backend and reporting checks:

```bash
harbor run \
  --dataset ./evals/kernel-mcp-server \
  --agent codex \
  --model openai/gpt-5.6 \
  --env harbor_hypeman:HypemanEnvironment \
  --plugin braintrust
```

The tasks start from fixed source commits and use focused hidden Bun tests for browser-region forwarding and MCP client-capability parsing.

## Behavior

- Dockerfile builds are cached by Harbor environment content hash and rebuilt with `--force-build`.
- Commands execute once through Hypeman's WebSocket API; transport failures after dispatch are not retried.
- Hypeman currently returns merged stdout/stderr. Harbor receives that output as `stdout` and `stderr=None`.
- Uploads and downloads use Hypeman's archive-aware WebSocket copy API.
- `stop(delete=False)` stops and preserves the instance; `stop(delete=True)` deletes it.

## Not supported

- Docker Compose or sidecar services
- network allowlists or runtime network-policy changes
- GPUs, TPUs, and Windows containers
- interactive `harbor ... --attach`
