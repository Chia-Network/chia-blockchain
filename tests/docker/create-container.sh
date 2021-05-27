#!/bin/sh

cat /app/pyvers.txt | while read PYVER ; do
    echo python "$PYVER"
    conda env create -f "environment$PYVER.yml"
    conda run -n "python$PYVER" sh install.sh
    conda run -n "python$PYVER" sh install-timelord.sh
    conda run -n "python$PYVER" python3 setup.py install
    conda run -n "python$PYVER" pip install pytest
    conda run -n "python$PYVER" pip install aiosqlite
    conda run -n "python$PYVER" pip install pytest-asyncio
done
