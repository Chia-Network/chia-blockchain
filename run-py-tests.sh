#!/bin/bash

git submodule update --init --recursive
python3 -m venv .venv
. .venv/bin/activate
pip3 install .

py.test ./tests -s -v