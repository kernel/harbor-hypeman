from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, override

from harbor.environments.base import (
    BaseEnvironment,
    ExecResult,
    SandboxBuildFailedError,
)
from harbor.environments.capabilities import (
    EnvironmentCapabilities,
    EnvironmentResourceCapabilities,
)
from harbor.environments.definition import (
    effective_exec_cwd,
    parse_dockerfile_workdir,
    require_agent_environment_definition,
    should_use_prebuilt_docker_image,
)
from harbor.models.task.config import EnvironmentConfig, NetworkMode
from harbor.models.trial.paths import TrialPaths
from hypeman import AsyncHypeman, NotFoundError, omit
from hypeman.lib import (
    cp_from_instance_async,
    cp_to_instance_async,
    exec_async,
)
from pathspec import GitIgnoreSpec

_BUILD_TAG = "harbor.environment_id"
_TERMINAL_BUILD_STATES = frozenset({"failed", "cancelled"})


class HypemanEnvironment(BaseEnvironment):
    """Run a single-container Harbor environment on Hypeman."""

    @classmethod
    @override
    def preflight(cls) -> None:
        if not os.environ.get("HYPEMAN_API_KEY"):
            raise SystemExit(
                "Hypeman requires HYPEMAN_API_KEY to be set. "
                "Set HYPEMAN_BASE_URL as well when the API is not on localhost."
            )

    def __init__(
        self,
        environment_dir: Path,
        environment_name: str,
        session_id: str,
        trial_paths: TrialPaths,
        task_env_config: EnvironmentConfig,
        *args: object,
        hypeman_client: AsyncHypeman | None = None,
        **kwargs: Any,
    ) -> None:
        self._client = hypeman_client or AsyncHypeman(max_retries=0)
        self._instance_id: str | None = None
        self._dockerfile_workdir = parse_dockerfile_workdir(
            environment_dir / "Dockerfile"
        )
        super().__init__(
            environment_dir=environment_dir,
            environment_name=environment_name,
            session_id=session_id,
            trial_paths=trial_paths,
            task_env_config=task_env_config,
            **kwargs,
        )

    @staticmethod
    @override
    def type() -> str:
        return "hypeman"

    @classmethod
    @override
    def resource_capabilities(cls) -> EnvironmentResourceCapabilities:
        return EnvironmentResourceCapabilities(cpu_limit=True, memory_limit=True)

    @property
    @override
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(disable_internet=True)

    @override
    def _validate_definition(self) -> None:
        require_agent_environment_definition(
            self.environment_dir,
            docker_image=self.task_env_config.docker_image,
        )
        if (self.environment_dir / "docker-compose.yaml").exists():
            raise ValueError(
                "Hypeman supports Dockerfile and prebuilt-image environments, "
                "not Docker Compose."
            )

    @override
    async def start(self, force_build: bool) -> None:
        if self._instance_id is not None:
            raise RuntimeError("Hypeman environment is already started.")

        image = await self._prepare_image(force_build)
        instance = await self._client.instances.create(
            image=image,
            name=self._instance_name(),
            entrypoint=["/bin/sh", "-c"],
            cmd=["while true; do sleep 3600; done"],
            env=self._startup_env(),
            network={"enabled": self.network_policy.network_mode == NetworkMode.PUBLIC},
            tags={
                "harbor.managed": "true",
                "harbor.environment_id": self.environment_id,
                "harbor.session_id": self.session_id,
            },
            vcpus=self._effective_cpus if self._effective_cpus is not None else omit,
            size=(
                f"{self._effective_memory_mb}MB"
                if self._effective_memory_mb is not None
                else omit
            ),
            overlay_size=(
                f"{self._effective_storage_mb}MB"
                if self._effective_storage_mb is not None
                else omit
            ),
        )
        self._instance_id = instance.id

        try:
            await self._client.instances.wait(
                instance.id,
                state="Running",
                api_timeout="5m",
                timeout=310,
            )
            await self._ensure_workdir()
            await self.ensure_dirs(self._mount_targets(writable_only=True))
            await self._upload_environment_dir_after_start()
        except BaseException:
            try:
                await self._client.instances.delete(instance.id)
            except Exception as cleanup_error:
                self.logger.warning(
                    "Failed to delete Hypeman instance %s after startup failed: %s",
                    instance.id,
                    cleanup_error,
                )
            finally:
                self._instance_id = None
            raise

    async def _ensure_workdir(self) -> None:
        workdir = self.task_env_config.workdir
        if workdir is None:
            return
        result = await self.exec(
            f"mkdir -p {shlex.quote(workdir)}",
            cwd="/",
            user="root",
        )
        if result.return_code != 0:
            raise RuntimeError(
                f"Failed to create Hypeman workdir {workdir!r}: "
                f"{result.stdout or 'no output'}"
            )

    async def _prepare_image(self, force_build: bool) -> str:
        docker_image = self.task_env_config.docker_image
        if should_use_prebuilt_docker_image(
            self.environment_dir,
            docker_image=docker_image,
            force_build=force_build,
        ):
            if docker_image is None:
                raise RuntimeError("Prebuilt image selection requires docker_image.")
            image = await self._client.images.create(
                name=docker_image,
                tags={_BUILD_TAG: self.environment_id},
            )
            return image.name

        if not force_build:
            cached_image = await self._cached_build_image()
            if cached_image is not None:
                return cached_image

        return await self._build_image()

    async def _cached_build_image(self) -> str | None:
        builds = await self._client.builds.list(tags={_BUILD_TAG: self.environment_id})
        for build in builds:
            if build.status != "ready" or build.image_ref is None:
                continue
            try:
                await self._client.images.get(build.image_ref)
            except NotFoundError:
                continue
            return build.image_ref
        return None

    async def _build_image(self) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "environment.tar.gz"
            await asyncio.to_thread(
                self._write_build_archive,
                self.environment_dir,
                archive_path,
            )
            with archive_path.open("rb") as source:
                build = await self._client.builds.create(
                    source=source,
                    tags=json.dumps({_BUILD_TAG: self.environment_id}),
                    timeout_seconds=int(self.task_env_config.build_timeout_sec),
                )

        deadline = (
            asyncio.get_running_loop().time() + self.task_env_config.build_timeout_sec
        )
        while build.status != "ready":
            if build.status in _TERMINAL_BUILD_STATES:
                raise SandboxBuildFailedError(
                    f"Hypeman build {build.id} ended in {build.status}: "
                    f"{build.error or 'no error details'}"
                )
            if asyncio.get_running_loop().time() >= deadline:
                await self._client.builds.cancel(build.id)
                raise TimeoutError(
                    f"Hypeman build {build.id} did not finish within "
                    f"{self.task_env_config.build_timeout_sec:g} seconds."
                )
            await asyncio.sleep(1)
            build = await self._client.builds.get(build.id)

        if build.image_ref is None:
            raise SandboxBuildFailedError(
                f"Hypeman build {build.id} completed without an image reference."
            )
        return build.image_ref

    @staticmethod
    def _write_build_archive(source_dir: Path, archive_path: Path) -> None:
        dockerignore_path = source_dir / ".dockerignore"
        dockerignore = (
            GitIgnoreSpec.from_lines(dockerignore_path.read_text().splitlines())
            if dockerignore_path.is_file()
            else None
        )

        with tarfile.open(archive_path, "w:gz") as archive:
            for path in sorted(source_dir.rglob("*")):
                relative = path.relative_to(source_dir)
                if {".git", "__pycache__"} & set(relative.parts):
                    continue
                archive_name = relative.as_posix()
                if (
                    dockerignore is not None
                    and archive_name not in {"Dockerfile", ".dockerignore"}
                    and dockerignore.match_file(
                        f"{archive_name}/" if path.is_dir() else archive_name
                    )
                ):
                    continue
                archive.add(path, arcname=archive_name, recursive=False)

    def _instance_name(self) -> str:
        session = re.sub(r"[^a-z0-9]+", "-", self.session_id.lower()).strip("-")
        if not session:
            session = "session"
        suffix = self.environment_id[:8]
        return f"harbor-{session[:46]}-{suffix}".strip("-")

    @override
    async def stop(self, delete: bool) -> None:
        if self._instance_id is None:
            return
        instance_id = self._instance_id
        if delete:
            await self._client.instances.delete(instance_id)
            self._instance_id = None
        else:
            await self._client.instances.stop(instance_id)

    def _require_instance(self) -> str:
        if self._instance_id is None:
            raise RuntimeError("Hypeman environment has not been started.")
        return self._instance_id

    @override
    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | int | None = None,
    ) -> ExecResult:
        user = self._resolve_user(user)
        if user not in (None, "root", 0):
            if isinstance(user, int):
                user_name = f"$(getent passwd {user} | cut -d: -f1)"
            else:
                user_name = shlex.quote(user)
            command = f"su {user_name} -s /bin/sh -c {shlex.quote(command)}"

        result = await exec_async(
            self._client,
            self._require_instance(),
            ["/bin/sh", "-lc", command],
            cwd=effective_exec_cwd(
                cwd,
                self.task_env_config.workdir,
                self._dockerfile_workdir,
            ),
            env=self._merge_env(env),
            timeout=timeout_sec,
        )
        output = result.output.decode("utf-8", errors="replace")
        callback = self._output_callback()
        if callback is not None and output:
            await callback(output, "stdout")
        return ExecResult(stdout=output, stderr=None, return_code=result.exit_code)

    @override
    async def upload_file(self, source_path: Path | str, target_path: str) -> None:
        await cp_to_instance_async(
            self._client,
            self._require_instance(),
            source_path,
            target_path,
            archive=True,
        )

    @override
    async def upload_dir(self, source_dir: Path | str, target_dir: str) -> None:
        await cp_to_instance_async(
            self._client,
            self._require_instance(),
            source_dir,
            target_dir,
            archive=True,
        )

    @override
    async def download_file(self, source_path: str, target_path: Path | str) -> None:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            await cp_from_instance_async(
                self._client,
                self._require_instance(),
                source_path,
                temp,
                archive=True,
            )
            downloaded = temp / PurePosixPath(source_path).name
            if not downloaded.is_file():
                raise RuntimeError(
                    f"Hypeman copy did not return the requested file {source_path!r}."
                )
            shutil.move(downloaded, target)

    @override
    async def download_dir(self, source_dir: str, target_dir: Path | str) -> None:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            await cp_from_instance_async(
                self._client,
                self._require_instance(),
                source_dir,
                temp,
                archive=True,
            )
            downloaded = temp / PurePosixPath(source_dir.rstrip("/")).name
            if not downloaded.is_dir():
                raise RuntimeError(
                    "Hypeman copy did not return the requested directory "
                    f"{source_dir!r}."
                )
            shutil.copytree(downloaded, target, dirs_exist_ok=True)
