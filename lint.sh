#!/bin/bash

clear

python3 -c "import sys; sys.exit(sys.prefix == sys.base_prefix)" || { echo "Not in a Python venv. Run '. ./activate'"; exit 1; }
venv_dir=$(python3 -c "import sys; print(sys.prefix);")

python3 -m pip install --upgrade pip mypy black flake8 isort | grep -v 'Requirement already satisfied:'

paths=$(git diff --name-only main | egrep 'py$')

${venv_dir}/bin/isort $paths
${venv_dir}/bin/black $paths
${venv_dir}/bin/flake8 --exclude venv $paths
${venv_dir}/bin/mypy $paths

