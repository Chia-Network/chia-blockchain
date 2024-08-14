#!/bin/bash

set -o errexit

USAGE_TEXT="\
Usage: $0 [-ch]

  -c                          command for Python
  -h                          display this help and exit
"

usage() {
  echo "${USAGE_TEXT}"
}

PYTHON_COMMAND=python

while getopts c:h flag; do
  case "${flag}" in
  c) PYTHON_COMMAND="${OPTARG}" ;;
  h)
    usage
    exit 0
    ;;
  *)
    echo
    usage
    exit 1
    ;;
  esac
done

"$PYTHON_COMMAND" -m venv .penv
.penv/bin/python -m pip install --upgrade pip setuptools wheel
# TODO: maybe make our own zipapp/shiv/pex of poetry and download that?
.penv/bin/python -m pip install poetry "poetry-dynamic-versioning[plugin]"
