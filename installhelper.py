#
# Install helper code to manage inserting the correct version for the GUI
# Gets the version from the result of "chia version"
# Converts to proper symver format so NPM doesn't complain
# Adds the version info to the package.json file
#
from __future__ import annotations

import json
import os
import shutil
import subprocess
from os.path import exists

from packaging.version import Version


#
# The following function is borrowed from
# https://github.com/inveniosoftware/invenio-assets/blob/maint-1.0/invenio_assets/npm.py
# Copyright (C) 2015-2018 CERN.
#
def make_semver(version_str: str) -> str:
    v = Version(version_str)
    major = v.release[0]
    try:
        minor = v.release[1]
    except IndexError:
        minor = 0
    try:
        patch = v.release[2]
    except IndexError:
        patch = 0

    prerelease = []
    if v.pre:
        prerelease.append("".join(str(x) for x in v.pre))
    if v.dev is not None:
        prerelease.append(f"dev{v.dev}")

    local = v.local

    version = f"{major}.{minor}.{patch}"

    if prerelease:
        version += f"-{'.'.join(prerelease)}"
    if local:
        version += f"+{local}"

    return version


def get_chia_version() -> str:
    version: str = "0.0"
    chia_executable = shutil.which("chia")
    if chia_executable is None:
        chia_executable = "chia"
    output = subprocess.run([chia_executable, "version"], capture_output=True)
    if output.returncode == 0:
        version = str(output.stdout.strip(), "utf-8").splitlines()[-1]
    return make_semver(version)


def update_version(package_json_path: str):
    if not exists(package_json_path):
        return

    with open(package_json_path) as f:
        data = json.load(f)

    data["version"] = get_chia_version()

    with open(package_json_path, "w") as w:
        json.dump(data, indent=2, fp=w)


if __name__ == "__main__":
    update_version(f"{os.path.dirname(__file__)}/chia-blockchain-gui/package.json")
    update_version(f"{os.path.dirname(__file__)}/chia-blockchain-gui/packages/gui/package.json")
