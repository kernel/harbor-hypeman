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

Commands launch as detached jobs inside the VM and use short Hypeman exec calls
to poll their status. The command and VM continue running when the Hypeman
control plane reconnects during a deployment.

The backend supports task environments defined by either:

- `[environment].docker_image` in `task.toml`
- `environment/Dockerfile`

CPU, memory, and storage values map to Hypeman vCPUs, base memory, and writable overlay size. Harbor `public` and `no-network` modes map to attached and detached Hypeman networking.

## Behavior

- Dockerfile builds are cached by Harbor environment content hash and rebuilt with `--force-build`.
- Commands run independently inside the VM, are polled with short exec calls, and tolerate control-plane interruptions of up to 60 seconds.
- Hypeman currently returns merged stdout/stderr. Harbor receives that output as `stdout` and `stderr=None`.
- Uploads and downloads use Hypeman's archive-aware WebSocket copy API.
- `stop(delete=False)` stops and preserves the instance; `stop(delete=True)` deletes it.

## Not supported

- Docker Compose or sidecar services
- network allowlists or runtime network-policy changes
- GPUs, TPUs, and Windows containers
- interactive `harbor ... --attach`
