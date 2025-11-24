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
    """Construct Singularity mount argument.

    Args:
        host_path: Path on the host filesystem to mount.
        container_path: Path inside the container where the host path will be mounted.
        readonly: If True, mount as read-only; otherwise mount as read-write.

    Returns:
        Formatted mount string in the format "host:container[:ro]".

    Raises:
        ValueError: If host_path or container_path contains illegal characters
            (comma, backslash, or colon).
    """
    # Check for illegal characters
    charset = set(host_path + container_path)
    if any(c in charset for c in r",\\:"):
        raise ValueError("Illegal characters in path")
    return f"{host_path}:{container_path}{':ro' if readonly else ''}"


class StyxSingularityError(StyxRuntimeError):
    """Styx Singularity runtime error.

    Raised when a Singularity container execution fails.
    """

    def __init__(
        self,
        return_code: int | None = None,
        command_args: list[str] | None = None,
        singularity_args: list[str] | None = None,
    ) -> None:
        """Create StyxSingularityError.

        Args:
            return_code: The exit code returned by the failed process.
            command_args: The command arguments that were executed inside the container.
            singularity_args: The Singularity-specific arguments used to run the
                container.
        """
        super().__init__(
            return_code=return_code,
            command_args=command_args,
            message_extra=f"- Singularity args: {shlex.join(singularity_args)}"
            if singularity_args
            else None,
        )


class _SingularityExecution(Execution):
    """Singularity execution context.

    Manages the execution of a command within a Singularity container,
    handling input/output file mounting and command execution.
    """

    def __init__(
        self,
        logger: logging.Logger,
        output_dir: pl.Path,
        metadata: Metadata,
        container_tag: str,
        singularity_executable: str,
        singularity_extra_args: list[str],
        environ: dict[str, str],
    ) -> None:
        """Create SingularityExecution.

        Args:
            logger: Logger instance for execution logging.
            output_dir: Directory where output files will be written.
            metadata: Metadata about the command being executed.
            container_tag: Singularity container image tag (e.g., "docker://ubuntu:20.04").
            singularity_executable: Path to the singularity executable.
            singularity_extra_args: Additional arguments to pass to singularity.
            environ: Environment variables to set in the container.
        """
        self.logger: logging.Logger = logger
        self.input_mounts: list[tuple[pl.Path, str, bool]] = []
        self.input_file_next_id = 0
        self.output_dir = output_dir
        self.metadata = metadata
        self.container_tag = container_tag
        self.singularity_executable = singularity_executable
        self.singularity_extra_args = singularity_extra_args
        self.environ = environ

    def input_file(
        self,
        host_file: InputPathType,
        resolve_parent: bool = False,
        mutable: bool = False,
    ) -> str:
        """Resolve input file path for container execution.

        Registers a host file to be mounted in the container and returns
        the path where it will be accessible inside the container.

        Args:
            host_file: Path to the input file on the host filesystem.
            resolve_parent: If True, mount the parent directory instead of just
                the file.
            mutable: If True, mount as read-write; otherwise mount as read-only.

        Returns:
            Path where the file will be accessible inside the container
                (e.g., "/styx_input/0/file.txt").

        Raises:
            FileNotFoundError: If the input file or parent directory doesn't exist.
        """
        _host_file = pl.Path(host_file)

        if resolve_parent:
            _host_file_parent = _host_file.parent
            if not _host_file_parent.is_dir():
                raise FileNotFoundError(
                    f'Input folder not found: "{_host_file_parent}"'
                )

            local_file = (
                f"/styx_input/{self.input_file_next_id}/{_host_file_parent.name}"
            )
            resolved_file = f"{local_file}/{_host_file.name}"
            self.input_mounts.append((_host_file_parent, local_file, mutable))
        else:
            if not _host_file.exists():
                raise FileNotFoundError(f'Input file not found: "{_host_file}"')

            resolved_file = local_file = (
                f"/styx_input/{self.input_file_next_id}/{_host_file.name}"
            )
            self.input_mounts.append((_host_file, local_file, mutable))

        self.input_file_next_id += 1
        return resolved_file

    def output_file(self, local_file: str, optional: bool = False) -> OutputPathType:
        """Resolve output file path.

        Args:
            local_file: Relative path of the output file within the output directory.
            optional: If True, the file is optional and may not be created
                (currently unused).

        Returns:
            Full path where the output file will be written on the host filesystem.
        """
        return self.output_dir / local_file

    def params(self, params: dict) -> dict:
        """Pass through parameters unchanged.

        Args:
            params: Command parameters dictionary.

        Returns:
            The same parameters dictionary, unmodified.
        """
        return params

    def run(
        self,
        cargs: list[str],
        handle_stdout: typing.Callable[[str], None] | None = None,
        handle_stderr: typing.Callable[[str], None] | None = None,
    ) -> None:
        """Execute the command in a Singularity container.

        Constructs the Singularity command with all necessary mounts and arguments,
        executes it, and handles stdout/stderr streams.

        Args:
            cargs: Command and arguments to execute inside the container.
            handle_stdout: Optional callback function to handle stdout lines.
                If None, logs to info level.
            handle_stderr: Optional callback function to handle stderr lines.
                If None, logs to error level.

        Raises:
            StyxSingularityError: If the command execution fails (non-zero exit code).
        """
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
            *self.singularity_extra_args,
            *mounts,
            *(["--env", environ_args_arg] if environ_args_arg else []),
            self.container_tag,
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
        self.logger.info(
            f"Executed {self.metadata.package} {self.metadata.name} "
            f"in {time_end - time_start}"
        )
        if return_code:
            raise StyxSingularityError(return_code, singularity_command, cargs)


class SingularityRunner(Runner):
    """Singularity container runner.

    Executes commands within Singularity containers, managing container images,
    file mounting, and execution environment.

    This runner is not supported on Windows platforms.
    """

    logger_name = "styx_singularity_runner"

    def __init__(
        self,
        image_overrides: dict[str, str] | None = None,
        singularity_executable: str = "singularity",
        singularity_extra_args: list[str] | None = None,
        data_dir: InputPathType | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        """Create a new SingularityRunner.

        Args:
            image_overrides: Dictionary mapping container image tags to alternative
                tags. Useful for using local or custom container images.
            singularity_executable: Path to the singularity executable. Defaults to
                "singularity" (assumes it's in PATH).
            singularity_extra_args: Additional arguments to pass to all
                singularity commands.
                Defaults to ["--no-mount", "hostfs"] to prevent automatic host
                filesystem mounting.
            data_dir: Directory for temporary execution data and outputs.
                Defaults to "styx_tmp" in the current directory.
            environ: Environment variables to set in all container executions.

        Raises:
            ValueError: If running on Windows (Singularity is not supported on Windows).
        """
        if os.name == "nt":
            raise ValueError("SingularityRunner is not supported on Windows")

        self.data_dir = pl.Path(data_dir or "styx_tmp")
        self.uid = os.urandom(8).hex()
        self.execution_counter = 0
        self.image_overrides = image_overrides or {}
        self.singularity_executable = singularity_executable
        self.singularity_extra_args = singularity_extra_args or ["--no-mount", "hostfs"]
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
        """Start a new execution context.

        Creates a new execution instance with a unique output directory
        and configured container image.

        Args:
            metadata: Metadata describing the command to execute, including
                the container image tag.

        Returns:
            Execution context for running commands in the container.

        Raises:
            ValueError: If metadata doesn't specify a container image tag.
        """
        if metadata.container_image_tag is None:
            raise ValueError("No container image tag specified in metadata")
        container_tag = self.image_overrides.get(
            metadata.container_image_tag, metadata.container_image_tag
        )
        if not container_tag.startswith("docker://"):
            container_tag = f"docker://{container_tag}"

        self.execution_counter += 1
        return _SingularityExecution(
            logger=self.logger,
            output_dir=self.data_dir
            / f"{self.uid}_{self.execution_counter - 1}_{metadata.name}",
            metadata=metadata,
            container_tag=container_tag,
            singularity_executable=self.singularity_executable,
            singularity_extra_args=self.singularity_extra_args,
            environ=self.environ,
        )
