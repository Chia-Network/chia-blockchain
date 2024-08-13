#!/bin/sh

set -o errexit

SCRIPT_DIRECTORY=$(
  cd -- "$(dirname -- "$0")"
  pwd
)

ENV_DIRECTORY="$1"
shift

# shellcheck disable=SC1090,SC1091
. "${SCRIPT_DIRECTORY}/${ENV_DIRECTORY}/bin/activate"

"$@"
