#!/bin/bash

python3 -m venv venv
# shellcheck disable=SC1091
. ./activate
pip3 install ".[dev]"
mypy --install-types

py.test ./tests -s -v
