""".. include:: ../../README.md"""  # noqa: D415

import logging
import os
import pathlib as pl
import shlex
import typing
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from subprocess import PIPE, Popen

from styxdefs import (
    Execution,
    InputPathType,
    Metadata,
    OutputPathType,
    Runner,
    StyxRuntimeError,
)


def _singularity_mount(host_path: str, container_path: str, readonly: bool) -> str:
    """Construct Singularity mount argument."""
    # Check for illegal characters
    charset = set(host_path + container_path)
    if any(c in charset for c in r",\\:"):
        raise ValueError("Illegal characters in path")
    return f"{host_path}:{container_path}{':ro' if readonly else ''}"


class StyxSingularityError(StyxRuntimeError):
    """Styx Singularity runtime error."""

    def __init__(
        self,
        return_code: int | None = None,
        command_args: list[str] | None = None,
        singularity_args: list[str] | None = None,
    ) -> None:
        """Create StyxSingularityError."""
        super().__init__(
            return_code=return_code,
            command_args=command_args,
            message_extra=f"- Singularity args: {shlex.join(singularity_args)}"
            if singularity_args
            else None,
        )


class _SingularityExecution(Execution):
    """Singularity execution."""

    def __init__(
        self,
        logger: logging.Logger,
        output_dir: pl.Path,
        metadata: Metadata,
        container_image: pl.Path,
        singularity_executable: str,
        environ: dict[str, str],
    ) -> None:
        """Create SingularityExecution."""
        self.logger: logging.Logger = logger
        self.input_mounts: list[tuple[pl.Path, str, bool]] = []
        self.input_file_next_id = 0
        self.output_dir = output_dir
        self.metadata = metadata
        self.container_image = container_image
        self.singularity_executable = singularity_executable
        self.environ = environ

    def input_file(
        self,
        host_file: InputPathType,
        resolve_parent: bool = False,
        mutable: bool = False,
    ) -> str:
        """Resolve input file."""
        _host_file = pl.Path(host_file)

        if resolve_parent:
            local_file = (
                f"/styx_input/{self.input_file_next_id}/{_host_file.parent.name}"
            )
            resolved_file = f"{local_file}/{_host_file.name}"
            self.input_mounts.append((_host_file.parent, local_file, mutable))
        else:
            resolved_file = local_file = (
                f"/styx_input/{self.input_file_next_id}/{_host_file.name}"
            )
            self.input_mounts.append((_host_file, local_file, mutable))

        self.input_file_next_id += 1
        return resolved_file

    def output_file(self, local_file: str, optional: bool = False) -> OutputPathType:
        """Resolve output file."""
        return self.output_dir / local_file

    def run(
        self,
        cargs: list[str],
        handle_stdout: typing.Callable[[str], None] | None = None,
        handle_stderr: typing.Callable[[str], None] | None = None,
    ) -> None:
        """Execute."""
        mounts: list[str] = []

        for host_file, local_file, mutable in self.input_mounts:
            mounts.append("--bind")
            mounts.append(
                _singularity_mount(
                    host_file.absolute().as_posix(), local_file, readonly=not mutable
                )
            )

        # Output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create run script
        run_script = self.output_dir / "run.sh"
        # Ensure utf-8 encoding and unix newlines
        run_script.write_text(
            f"#!/bin/bash\ncd /styx_output\n{shlex.join(cargs)}\n",
            encoding="utf-8",
            newline="\n",
        )

        mounts.append("--bind")
        mounts.append(
            _singularity_mount(
                self.output_dir.absolute().as_posix(), "/styx_output", readonly=False
            )
        )

        environ_args_arg = ",".join(
            [f"{key}={value}" for key, value in self.environ.items()]
        )

        singularity_command = [
            self.singularity_executable,
            "exec",
            *mounts,
            *(["--env", environ_args_arg] if environ_args_arg else []),
            self.container_image.as_posix(),
            "/bin/bash",
            "/styx_output/run.sh",
        ]

        self.logger.debug(f"Running singularity: {shlex.join(singularity_command)}")
        self.logger.debug(f"Running command: {shlex.join(cargs)}")

        _stdout_handler = (
            handle_stdout if handle_stdout else lambda line: self.logger.info(line)
        )
        _stderr_handler = (
            handle_stderr if handle_stderr else lambda line: self.logger.error(line)
        )

        time_start = datetime.now()
        with Popen(singularity_command, text=True, stdout=PIPE, stderr=PIPE) as process:
            with ThreadPoolExecutor(2) as pool:  # two threads to handle the streams
                exhaust = partial(pool.submit, partial(deque, maxlen=0))
                exhaust(_stdout_handler(line[:-1]) for line in process.stdout)  # type: ignore
                exhaust(_stderr_handler(line[:-1]) for line in process.stderr)  # type: ignore
        return_code = process.poll()
        time_end = datetime.now()
        self.logger.info(f"Executed {self.metadata.name} in {time_end - time_start}")
        if return_code:
            raise StyxSingularityError(return_code, singularity_command, cargs)


class SingularityRunner(Runner):
    """Singularity runner."""

    logger_name = "styx_singularity_runner"

    def __init__(
        self,
        images: dict[str, str | pl.Path] | None = None,
        singularity_executable: str = "singularity",
        data_dir: InputPathType | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        """Create a new SingularityRunner.

        images is a dictionary of container image tags to paths.
        """
        if os.name == "nt":
            raise ValueError("SingularityRunner is not supported on Windows")

        self.data_dir = pl.Path(data_dir or "styx_tmp")
        self.uid = os.urandom(8).hex()
        self.execution_counter = 0
        self.images = images or {}
        self.singularity_executable = singularity_executable
        self.environ = environ or {}

        # Configure logger
        self.logger = logging.getLogger(self.logger_name)
        if not self.logger.hasHandlers():
            self.logger.setLevel(logging.DEBUG)
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            formatter = logging.Formatter("[%(levelname).1s] %(message)s")
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)

    def start_execution(self, metadata: Metadata) -> Execution:
        """Start execution."""
        if metadata.container_image_tag is None:
            raise ValueError("No container image tag specified in metadata")
        if (container_path := self.images.get(metadata.container_image_tag)) is None:
            raise ValueError(
                f"Container image path not found: {metadata.container_image_tag}. "
                f"Use `singularity pull docker://{metadata.container_image_tag} "
                f"[output file]`  to download it and specify it in the `images` "
                f"argument of the runner."
            )

        self.execution_counter += 1
        return _SingularityExecution(
            logger=self.logger,
            output_dir=self.data_dir
            / f"{self.uid}_{self.execution_counter - 1}_{metadata.name}",
            metadata=metadata,
            container_image=pl.Path(container_path),
            singularity_executable=self.singularity_executable,
            environ=self.environ,
        )
