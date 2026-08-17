#!/usr/bin/env bash
set -u
mkdir -p /logs/verifier
cp /tests/browser-region.test.ts /workspace/src/lib/mcp/tools/harbor-browser-region.test.ts
cd /workspace
bun test src/lib/mcp/tools/harbor-browser-region.test.ts 2>&1 | tee /logs/verifier/test-output.txt
status=${PIPESTATUS[0]}
if [ "$status" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
exit "$status"
