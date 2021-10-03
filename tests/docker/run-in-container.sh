#!/bin/sh

PYVER="${1}"
rm -rf ./venv "/py/venv${PYVER}"
export PATH="./venv/bin:${PATH}"
export VENV_DIR="/py/venv$PYVER"
sh install.sh
. "${VENV_DIR}/bin/activate"
sh install-timelord.sh
pip install pytest
pip install aiosqlite
pip install pytest-asyncio
pip install -e .
