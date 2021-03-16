#!/bin/bash

python3 -m venv venv
# shellcheck disable=SC1091
. ./activate
pip3 install .

py.test ./tests/blockchain/test_weight_proof.py -s -v --durations 0 -n auto
py.test ./tests/blockchain --ignore tests/blockchain/test_weight_proof.py -s -v --durations 0

py.test ./tests/core -s -v --durations 0 -n auto
py.test ./tests/clvm -s -v --durations 0 -n auto
py.test ./tests/simulation -s -v --durations 0
py.test ./tests/wallet -s -v --durations 0

py.test ./tests/non_parallel -s -v --durations 0
