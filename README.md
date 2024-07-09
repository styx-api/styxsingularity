# Singularity/Apptainer Runner for Styx compiled wrappers

[![Build](https://github.com/childmindresearch/styxsingularity/actions/workflows/test.yaml/badge.svg?branch=main)](https://github.com/childmindresearch/styxsingularity/actions/workflows/test.yaml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/childmindresearch/styxsingularity/branch/main/graph/badge.svg?token=22HWWFWPW5)](https://codecov.io/gh/childmindresearch/styxsingularity)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
![stability-stable](https://img.shields.io/badge/stability-stable-green.svg)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/childmindresearch/styxsingularity/blob/main/LICENSE)
[![pages](https://img.shields.io/badge/api-docs-blue)](https://childmindresearch.github.io/styxsingularity)

## Usage

```Python
from styxdefs import set_global_runner
from styxsingularity import SingularityRunner

set_global_runner(SingularityRunner())

# Now you can use any Styx functions as usual
```
