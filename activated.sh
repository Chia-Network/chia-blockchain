#!/bin/bash

set -o errexit

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "$0")"; pwd)
source "${SCRIPT_DIRECTORY}/venv/bin/activate"

"$@"
