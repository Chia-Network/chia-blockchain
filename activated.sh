#!/bin/bash

set -o errexit

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "$0")"; pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIRECTORY}/venv/bin/activate"

"$@"
