# Singularity/Apptainer Runner for Styx compiled wrappers

[![Build](https://github.com/childmindresearch/styxsingularity/actions/workflows/test.yaml/badge.svg?branch=main)](https://github.com/childmindresearch/styxsingularity/actions/workflows/test.yaml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/childmindresearch/styxsingularity/branch/main/graph/badge.svg?token=22HWWFWPW5)](https://codecov.io/gh/childmindresearch/styxsingularity)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
![stability-stable](https://img.shields.io/badge/stability-stable-green.svg)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/childmindresearch/styxsingularity/blob/main/LICENSE)
[![pages](https://img.shields.io/badge/api-docs-blue)](https://childmindresearch.github.io/styxsingularity)

`styxsingularity` is a Python package that provides Singularity/Apptainer integration for Styx compiled wrappers. It allows you to run Styx functions within Singularity containers, offering improved isolation and reproducibility for your workflows.

## Installation

You can install `styxsingularity` using pip:

```Python
pip install styxsingularity
```

## Usage

```Python
from styxdefs import set_global_runner
from styxsingularity import SingularityRunner

# Initialize the SingularityRunner with your container images
runner = SingularityRunner(
    images={
        "ubuntu:20.04": "/path/to/ubuntu_20.04.sif",
        "python:3.9": "/path/to/python_3.9.sif"
    }
)

# Set the global runner for Styx
set_global_runner(runner)

# Now you can use any Styx functions as usual, and they will run in Singularity containers
```

## Advanced Configuration

The `SingularityRunner` class accepts several parameters for advanced configuration:

- `images`: A dictionary mapping container image tags to their local paths
- `singularity_executable`: Path to the Singularity executable (default: `"singularity"`)
- `data_dir`: Directory for temporary data storage
- `environ`: Environment variables to set in the container

Example:

```python
runner = SingularityRunner(
    images={"ubuntu:20.04": "/path/to/ubuntu_20.04.sif"},
    singularity_executable="/usr/local/bin/singularity",
    data_dir="/tmp/styx_data",
    environ={"PYTHONPATH": "/app/lib"}
)
```

## Error Handling

`styxsingularity` provides a custom error class, `StyxSingularityError`, which is raised when a Singularity execution fails. This error includes details about the return code, command arguments, and Singularity arguments for easier debugging.

## Contributing

Contributions to `styxsingularity` are welcome! Please refer to the [GitHub repository](https://github.com/childmindresearch/styxsingularity) for information on how to contribute, report issues, or submit pull requests.

## License

`styxsingularity` is released under the MIT License. See the LICENSE file for details.

## Documentation

For detailed API documentation, please visit our [API Docs](https://childmindresearch.github.io/styxsingularity).

## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/childmindresearch/styxsingularity).

## Requirements

- Python 3.10+
- Singularity or Apptainer installed and running on your system

## Comparison with [`styxdocker`](https://github.com/childmindresearch/styxdocker)

While [`styxdocker`](https://github.com/childmindresearch/styxdocker) and [`styxsingularity`](https://github.com/childmindresearch/styxsingularity) serve similar purposes, they have some key differences:

- Container Technology: `styxdocker` uses Docker, while `styxsingularity` uses Singularity/Apptainer.
- Platform Support: `styxdocker` works on Windows, Linux, and macOS, whereas `styxsingularity` is not supported on Windows.
- User Permissions: `styxdocker` can run containers as the current user on POSIX systems, which can help with file permission issues.

Choose the package that best fits your infrastructure and requirements.
