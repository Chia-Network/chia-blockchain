#!/bin/sh

set -o errexit

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "$0")"; pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIRECTORY}/venv/bin/activate"

"$@"
