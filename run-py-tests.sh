#!/bin/bash

python3 -m venv venv
. ./activate
pip3 install .

py.test ./tests -s -v