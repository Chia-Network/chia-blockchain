#!/bin/bash

from __future__ import annotations

echo -n "OS: "
uname -a
echo -n "sqlite3: "
sqlite3 --version
echo -n "black: "
black --version
echo -n "mypy: "
mypy --version
echo -n "flake8: "
flake8 --version
echo -n "isort: "
isort --version
