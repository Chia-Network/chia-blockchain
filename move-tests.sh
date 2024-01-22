#!/bin/bash

# git reset -- . && git checkout -- . && rm -rf chia/_tests/

set -vx

git mv tests/ chia/_tests/
find chia/_tests/ benchmarks/ tools/ -name '*.py' -exec sed -i -E 's/(from|import) tests/\1 chia._tests/' {} \;
python tools/manage_clvm.py build

for _ in {1..2}
do
  git add --update
  venv/bin/pre-commit run --all-files
done
