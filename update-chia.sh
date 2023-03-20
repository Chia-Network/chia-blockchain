#!/bin/bash

pip install --upgrade pip
rm -rf venv
python3 -m venv venv
. ./activate
pip install -e .\[dev\]

