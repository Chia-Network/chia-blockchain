#!/usr/bin/env bash
set -eo pipefail

# Removes rpath loader commands from _ssl.cpython-*.so which are sometimes
# added on Apple M-series CPUs, prefer bundled dynamic libraries for which
# there is an rpath added already as "@loader_path/.." -- however, the
# homebrew rpaths appear with higher precedence, potentially causing issues.
# See: #18099

echo ""
echo "Stripping brew rpaths..."

rpath_name=/opt/homebrew/lib

so_path=$(find "dist/daemon/_internal/lib-dynload" -name "_ssl.cpython-*.so")
if [[ -z "${so_path}" ]]; then
  >&2 echo "Failed to find _ssl.cpython-*.so"
fi

echo "Found '_ssl.cpython-*.so' at '$so_path':"
otool -l "$so_path"
echo ""

set +e
nt_output=
r=0
while [[ $r -eq 0 ]]; do
  install_name_tool -delete_rpath $rpath_name "$so_path" 2>&1 | read -r nt_output
  r=$?
done

if [[ -n "$nt_output" ]]; then
  echo "$nt_output" | grep "no LC_RPATH load command with path:" >/dev/null
  # shellcheck disable=SC2181
  if [[ $? -ne 0 ]]; then
    >&2 echo "An unexpected error occurred when running install_name_tool:"
    >&2 echo "$nt_output"
  fi
fi

echo "Done."
echo ""
