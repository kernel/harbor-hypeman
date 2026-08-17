---
name: release
description: Release harbor-hypeman to PyPI and GitHub. Use when asked to publish, release, cut a version, bump the package version, or verify a harbor-hypeman release.
---

# Release harbor-hypeman

Publish immutable releases from version tags on `main`. PyPI authentication uses the `pypi` GitHub environment and Trusted Publishing; never add an API token.

## Prepare the version

1. Fetch `origin` and require a clean working tree.
2. Read the version from `pyproject.toml` and the latest `v*` tag.
3. If the current version is already greater than the latest tag, use it. Otherwise create a `hypeship/release-vX.Y.Z` branch and update:
   - `project.version` in `pyproject.toml`
   - the matching package version in `uv.lock` by running `uv lock`
   - `CHANGELOG.md`, moving relevant entries from `Unreleased` into a dated version section
4. Run:

   ```bash
   uv sync --locked --dev
   uv run ruff format --check .
   uv run ruff check .
   uv run ty check
   uv run pytest
   uv build
   ```

5. Commit, push, and open a ready-for-review release PR. Wait for required CI, BugBot, and review before merging.

## Publish

1. Return to `main`, fast-forward to `origin/main`, and verify the release workflow and version bump are present.
2. Require the release commit to be exactly `origin/main` and confirm the tag does not already exist locally or remotely.
3. Create and push an annotated tag:

   ```bash
   git tag -a "vX.Y.Z" -m "Release vX.Y.Z"
   git push origin "vX.Y.Z"
   ```

4. Watch the `Release` workflow until it succeeds. It verifies the tag and version, runs all checks, publishes with PyPI Trusted Publishing, and creates the GitHub release.
5. Verify both release surfaces:

   ```bash
   gh release view "vX.Y.Z"
   curl -fsSL https://pypi.org/pypi/harbor-hypeman/json | jq -e '.info.version == "X.Y.Z"'
   uv run --isolated --with "harbor-hypeman==X.Y.Z" python -c 'import harbor_hypeman'
   ```

Never reuse a version already published to PyPI. If publication succeeded but a later step failed, repair that step without moving or recreating the tag.
