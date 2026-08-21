from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from harbor.environments.base import SandboxBuildFailedError
from harbor.environments.factory import EnvironmentFactory
from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
from harbor.models.trial.config import EnvironmentConfig as TrialEnvironmentConfig
from harbor.models.trial.paths import TrialPaths
from hypeman import AsyncHypeman, NotFoundError

import harbor_hypeman.environment as environment_module
from harbor_hypeman import HypemanEnvironment


def _client() -> Any:
    client = MagicMock()
    client.images.create = AsyncMock(
        return_value=SimpleNamespace(name="docker.io/library/alpine:latest")
    )
    response = httpx.Response(404, request=httpx.Request("GET", "https://example.com"))
    client.images.get = AsyncMock(
        side_effect=NotFoundError("missing", response=response, body=None)
    )
    client.builds.list = AsyncMock(return_value=[])
    client.builds.create = AsyncMock()
    client.builds.get = AsyncMock()
    client.builds.cancel = AsyncMock()
    client.instances.create = AsyncMock(return_value=SimpleNamespace(id="instance-1"))
    client.instances.wait = AsyncMock()
    client.instances.stop = AsyncMock()
    client.instances.delete = AsyncMock()
    return client


def _environment(
    tmp_path: Path,
    *,
    task_config: EnvironmentConfig | None = None,
    network_policy: NetworkPolicy | None = None,
    client: Any | None = None,
    dockerfile: str | None = None,
) -> HypemanEnvironment:
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    if dockerfile is not None:
        (environment_dir / "Dockerfile").write_text(dockerfile)
    trial_paths = TrialPaths(tmp_path / "trial")
    trial_paths.mkdir()
    return HypemanEnvironment(
        environment_dir=environment_dir,
        environment_name="test-task",
        session_id="Test_Task__abc123__env",
        trial_paths=trial_paths,
        task_env_config=task_config
        or EnvironmentConfig(docker_image="docker.io/library/alpine:latest"),
        network_policy=network_policy or NetworkPolicy(),
        hypeman_client=cast(AsyncHypeman, client or _client()),
    )


def test_custom_environment_loads_from_import_path(tmp_path: Path) -> None:
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    trial_paths = TrialPaths(tmp_path / "trial")
    trial_paths.mkdir()

    result = EnvironmentFactory.create_environment_from_config(
        TrialEnvironmentConfig(import_path="harbor_hypeman:HypemanEnvironment"),
        environment_dir=environment_dir,
        environment_name="test-task",
        session_id="session",
        trial_paths=trial_paths,
        task_env_config=EnvironmentConfig(docker_image="alpine:latest"),
        hypeman_client=cast(AsyncHypeman, _client()),
    )

    assert isinstance(result, HypemanEnvironment)
    assert result.type() == "hypeman"


def test_capabilities_cover_limits_and_static_no_network(tmp_path: Path) -> None:
    environment = _environment(tmp_path)

    assert environment.capabilities.disable_internet is True
    assert environment.capabilities.network_allowlist is False
    assert environment.capabilities.dynamic_network_policy is False
    assert environment.resource_capabilities().cpu_limit is True
    assert environment.resource_capabilities().memory_limit is True


def test_allowlist_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allowlist.*not supported"):
        _environment(
            tmp_path,
            network_policy=NetworkPolicy(
                network_mode=NetworkMode.ALLOWLIST,
                allowed_hosts=["example.com"],
            ),
        )


async def test_start_prebuilt_image_maps_resources_and_network(tmp_path: Path) -> None:
    client = _client()
    environment = _environment(
        tmp_path,
        task_config=EnvironmentConfig(
            docker_image="docker.io/library/alpine:latest",
            cpus=2,
            memory_mb=2048,
            storage_mb=4096,
            env={"TASK_ENV": "value"},
        ),
        network_policy=NetworkPolicy(network_mode=NetworkMode.NO_NETWORK),
        client=client,
    )

    await environment.start(force_build=False)

    client.images.create.assert_awaited_once_with(
        name="docker.io/library/alpine:latest",
        tags={"harbor.environment_id": environment.environment_id},
    )
    create_kwargs = client.instances.create.await_args.kwargs
    assert create_kwargs["image"] == "docker.io/library/alpine:latest"
    assert create_kwargs["vcpus"] == 2
    assert create_kwargs["size"] == "2048MB"
    assert create_kwargs["overlay_size"] == "4096MB"
    assert create_kwargs["network"] == {"enabled": False}
    assert create_kwargs["name"].startswith("harbor-test-task-abc123-env-")
    assert create_kwargs["env"] == {
        "TASK_ENV": "value",
        "HYPEMAN_INSTANCE_NAME": create_kwargs["name"],
    }
    client.instances.wait.assert_awaited_once_with(
        "instance-1",
        state="Running",
        api_timeout="5m",
        timeout=310,
    )


async def test_start_uses_existing_prebuilt_image(tmp_path: Path) -> None:
    client = _client()
    client.images.get.side_effect = None
    client.images.get.return_value = SimpleNamespace(
        name="docker.io/builds/build-1:latest",
        status="ready",
    )
    environment = _environment(
        tmp_path,
        task_config=EnvironmentConfig(docker_image="builds/build-1"),
        client=client,
    )

    await environment.start(force_build=False)

    client.images.get.assert_awaited_once_with("builds/build-1")
    client.images.create.assert_not_awaited()
    assert client.instances.create.await_args.kwargs["image"] == "builds/build-1"


async def test_start_creates_configured_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client()
    environment = _environment(
        tmp_path,
        task_config=EnvironmentConfig(
            docker_image="alpine:latest",
            workdir="/workspace with spaces",
        ),
        client=client,
    )
    execute = AsyncMock(return_value=SimpleNamespace(output=b"", exit_code=0))
    monkeypatch.setattr(environment_module, "exec_async", execute)

    await environment.start(force_build=False)

    args = execute.await_args
    if args is None:
        raise AssertionError("workdir command was not executed")
    assert args.args[:3] == (
        client,
        "instance-1",
        ["/bin/bash", "-lc", "mkdir -p '/workspace with spaces'"],
    )
    assert args.kwargs["cwd"] == "/"


async def test_start_builds_dockerfile_context(tmp_path: Path) -> None:
    client = _client()
    client.builds.create.return_value = SimpleNamespace(
        id="build-1",
        status="ready",
        image_ref="registry.local/builds/build-1",
        error=None,
    )
    task_config = EnvironmentConfig(build_timeout_sec=30)
    environment = _environment(
        tmp_path,
        task_config=task_config,
        client=client,
        dockerfile="FROM alpine:3.22\nWORKDIR /workspace\n",
    )
    (environment.environment_dir / "payload.txt").write_text("payload")

    archive_names: set[str] = set()

    async def create_build(*, source: Any, **kwargs: Any) -> Any:
        with tarfile.open(fileobj=io.BytesIO(source.read()), mode="r:gz") as archive:
            archive_names.update(archive.getnames())
        assert kwargs["tags"] == json.dumps(
            {"harbor.environment_id": environment.environment_id}
        )
        assert kwargs["timeout_seconds"] == 30
        return SimpleNamespace(
            id="build-1",
            status="ready",
            image_ref="registry.local/builds/build-1",
            error=None,
        )

    client.builds.create.side_effect = create_build

    await environment.start(force_build=False)

    assert {"Dockerfile", "payload.txt"} <= archive_names
    assert client.instances.create.await_args.kwargs["image"] == (
        "registry.local/builds/build-1"
    )


async def test_failed_build_stops_before_instance_creation(tmp_path: Path) -> None:
    client = _client()
    client.builds.create.return_value = SimpleNamespace(
        id="build-1",
        status="failed",
        image_ref=None,
        error="Dockerfile failed",
    )
    environment = _environment(
        tmp_path,
        task_config=EnvironmentConfig(),
        client=client,
        dockerfile="FROM invalid\n",
    )

    with pytest.raises(SandboxBuildFailedError, match="Dockerfile failed"):
        await environment.start(force_build=True)

    client.instances.create.assert_not_awaited()


async def test_start_failure_deletes_created_instance(tmp_path: Path) -> None:
    client = _client()
    client.instances.wait.side_effect = RuntimeError("boot failed")
    environment = _environment(tmp_path, client=client)

    with pytest.raises(RuntimeError, match="boot failed"):
        await environment.start(force_build=False)

    client.instances.delete.assert_awaited_once_with("instance-1")
    assert environment._instance_id is None


async def test_start_reuses_ready_build(tmp_path: Path) -> None:
    client = _client()
    client.images.get.side_effect = None
    client.builds.list.return_value = [
        SimpleNamespace(
            status="ready",
            image_ref="registry.local/builds/cached",
        )
    ]
    environment = _environment(
        tmp_path,
        task_config=EnvironmentConfig(),
        client=client,
        dockerfile="FROM alpine:3.22\n",
    )

    await environment.start(force_build=False)

    client.images.get.assert_awaited_once_with("registry.local/builds/cached")
    client.builds.create.assert_not_awaited()
    assert client.instances.create.await_args.kwargs["image"] == (
        "registry.local/builds/cached"
    )


def test_build_archive_honors_dockerignore(tmp_path: Path) -> None:
    source_dir = tmp_path / "environment"
    source_dir.mkdir()
    (source_dir / "Dockerfile").write_text("FROM alpine:3.22\n")
    (source_dir / ".dockerignore").write_text(
        "Dockerfile\n.dockerignore\nsecret.txt\nignored/\n"
    )
    (source_dir / "keep.txt").write_text("keep")
    (source_dir / "secret.txt").write_text("secret")
    (source_dir / "ignored").mkdir()
    (source_dir / "ignored" / "file.txt").write_text("ignored")
    archive_path = tmp_path / "environment.tar.gz"

    HypemanEnvironment._write_build_archive(source_dir, archive_path)

    with tarfile.open(archive_path, "r:gz") as archive:
        names = set(archive.getnames())
    assert {"Dockerfile", ".dockerignore", "keep.txt"} <= names
    assert {"secret.txt", "ignored", "ignored/file.txt"}.isdisjoint(names)


async def test_exec_uses_shell_workdir_environment_and_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client()
    environment = _environment(
        tmp_path,
        task_config=EnvironmentConfig(
            docker_image="alpine:latest",
            workdir="/workspace",
            env={"PERSISTENT": "one"},
        ),
        client=client,
    )
    environment._instance_id = "instance-1"
    execute = AsyncMock(
        return_value=SimpleNamespace(output=b"combined output\n", exit_code=7)
    )
    monkeypatch.setattr(environment_module, "exec_async", execute)

    result = await environment.exec(
        "printf test",
        env={"PER_COMMAND": "two"},
        user="agent",
        timeout_sec=15,
    )

    assert result.stdout == "combined output\n"
    assert result.stderr is None
    assert result.return_code == 7
    args = execute.await_args
    if args is None:
        raise AssertionError("exec_async was not awaited")
    assert args.args[:3] == (
        client,
        "instance-1",
        ["/bin/bash", "-lc", "su agent -s /bin/sh -c 'printf test'"],
    )
    assert args.kwargs == {
        "cwd": "/workspace",
        "env": {"PERSISTENT": "one", "PER_COMMAND": "two"},
        "timeout": 15,
    }


async def test_file_transfers_preserve_harbor_target_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment(tmp_path)
    environment._instance_id = "instance-1"
    upload = AsyncMock()

    async def download(
        client: Any,
        instance_id: str,
        source_path: str,
        destination: Path,
        **kwargs: Any,
    ) -> None:
        assert client is environment._client
        assert instance_id == "instance-1"
        assert kwargs == {"archive": True}
        if source_path == "/remote/file.txt":
            (destination / "file.txt").write_text("file")
        else:
            root = destination / "source"
            root.mkdir()
            (root / "nested.txt").write_text("directory")

    monkeypatch.setattr(environment_module, "cp_to_instance_async", upload)
    monkeypatch.setattr(environment_module, "cp_from_instance_async", download)

    local_file = tmp_path / "upload.txt"
    local_file.write_text("upload")
    await environment.upload_file(local_file, "/remote/upload.txt")
    upload.assert_awaited_once_with(
        environment._client,
        "instance-1",
        local_file,
        "/remote/upload.txt",
        archive=True,
    )

    downloaded_file = tmp_path / "downloads" / "renamed.txt"
    await environment.download_file("/remote/file.txt", downloaded_file)
    assert downloaded_file.read_text() == "file"

    downloaded_dir = tmp_path / "directory"
    await environment.download_dir("/remote/source", downloaded_dir)
    assert (downloaded_dir / "nested.txt").read_text() == "directory"


async def test_stop_preserves_or_deletes_instance(tmp_path: Path) -> None:
    client = _client()
    environment = _environment(tmp_path, client=client)
    environment._instance_id = "instance-1"

    await environment.stop(delete=False)
    client.instances.stop.assert_awaited_once_with("instance-1")
    assert environment._instance_id == "instance-1"

    await environment.stop(delete=True)
    client.instances.delete.assert_awaited_once_with("instance-1")
    assert environment._instance_id is None
