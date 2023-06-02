#!/bin/bash

pwd
# PULL IN LICENSES USING NPM - LICENSE CHECKER
npm install -g license-checker

cd ../chia-blockchain-gui || 'exit" or "cd' ... || return
#npm install . - We do not want this to update

pwd
ls -lah
npm
sum=$(license-checker --summary)
printf "%s\n" "$sum"

license_list=$(license-checker --json | jq -r '.[].licenseFile' | grep -v null)

# Split the license list by newline character into an array
IFS=$'\n' read -rd '' -a licenses_array <<< "$license_list"

#print the contents of the array
printf '%s\n' "${licenses_array[@]}"

for i in "${licenses_array[@]}"; do
    dirname="licenses/$(dirname "$i" | awk -F'/' '{print $NF}')"
    mkdir -p "$dirname"
    echo "$dirname"
    cp "$i" "$dirname"
done

ls -lah licenses
mv licenses/ ../build_scripts/dist
cd ../build_scripts || 'exit" or "cd' || return
ls -lah dist/

python3 -m venv ../venv
. ../venv/bin/activate
# PULL IN THE LICENSES FROM PIP-LICENSE
pip install pip-licenses || pip3 install pip-licenses

# capture the output of the command in a variable
output=$(pip-licenses -l -f json | jq -r '.[].LicenseFile' | grep -v UNKNOWN)

# initialize an empty array
license_path_array=()

# read the output line by line into the array
while IFS= read -r line; do
    license_path_array+=("$line")
done <<< "$output"

# create a dir for each license and copy the license file over
for i in "${license_path_array[@]}"; do
  dirname="dist/licenses/$(dirname "$i" | awk -F'/' '{print $NF}')"
  echo "$dirname"
  mkdir -p "$dirname"
  cp "$i" "$dirname"
  echo "$i"
done

pwd

deactivate
