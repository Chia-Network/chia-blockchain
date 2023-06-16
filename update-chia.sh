#!/bin/bash

pip install --upgrade pip
rm -rf venv
python3 -m venv venv
# shellcheck disable=SC1091
. ./venv/bin/activate
pip install -e .\[dev\]
