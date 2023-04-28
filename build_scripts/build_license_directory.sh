#!/bin/bash

# PULL IN LICENSES USING NPM - LICENSE CHECKER

cd $HOME/chia-blockchain/chia-blockchain-gui

license_list=$(license-checker --json | jq -r '.[].licenseFile' | grep -v null)

# Split the license list by newline character into an array
IFS=$'\n' read -rd '' -a licenses <<< "$license_list"

# print the contents of the array
#printf '%s\n' "${licenses[@]}"

cd ..
for i in "${licenses[@]}"; do
  dirname="Licenses/$(dirname "$i" | awk -F'/' '{print $NF}')"
  mkdir -p "$dirname"
  cp "$i" "$dirname"
done

# PULL IN THE LICENSES FROM PIP-LICENSE

# capture the output of the command in a variable
output=$(pip-licenses -l -f json | jq -r '.[].LicenseFile' | grep -v UNKNOWN)

# initialize an empty array
license_path_array=()

# read the output line by line into the array
while IFS= read -r line; do
    license_path_array+=("$line")
done <<< "$output"

# print the contents of the array
printf '%s\n' "${license_path_array[@]}"

cd "$HOME/chia-blockchain"

# create a dir for each license and copy the license file over
for i in "${license_path_array[@]}"; do
  dirname="Licenses/$(dirname "$i" | awk -F'/' '{print $NF}')"
  echo "$dirname"
  if [ ! -d "$dirname" ]; then
    mkdir -p "$dirname"
  fi
  cp "$i" "$dirname"
done
