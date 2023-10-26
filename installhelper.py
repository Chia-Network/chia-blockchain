#
# Install helper code to manage inserting the correct version for the GUI
# Gets the version from the result of "chia version"
# Converts to proper symver format so NPM doesn't complain
# Adds the version info to the package.json file
#
from __future__ import annotations

import json
import os
import subprocess
from os.path import exists

from pkg_resources import parse_version


#
# The following function is borrowed from
# https://github.com/inveniosoftware/invenio-assets/blob/maint-1.0/invenio_assets/npm.py
# Copyright (C) 2015-2018 CERN.
#
def make_semver(version_str: str) -> str:
    v = parse_version(version_str)
    major = v._version.release[0]  # type: ignore[attr-defined]
    try:
        minor = v._version.release[1]  # type: ignore[attr-defined]
    except IndexError:
        minor = 0
    try:
        patch = v._version.release[2]  # type: ignore[attr-defined]
    except IndexError:
        patch = 0

    prerelease = []
    if v._version.pre:  # type: ignore[attr-defined]
        prerelease.append("".join(str(x) for x in v._version.pre))  # type: ignore[attr-defined]
    if v._version.dev:  # type: ignore[attr-defined]
        prerelease.append("".join(str(x) for x in v._version.dev))  # type: ignore[attr-defined]

    local = v.local

    version = f"{major}.{minor}.{patch}"

    if prerelease:
        version += "-{}".format(".".join(prerelease))
    if local:
        version += f"+{local}"

    return version


def get_chia_version() -> str:
    version: str = "0.0"
    output = subprocess.run(["chia", "version"], capture_output=True)
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
        json.dump(data, indent=4, fp=w)


if __name__ == "__main__":
    update_version(f"{os.path.dirname(__file__)}/chia-blockchain-gui/package.json")
    update_version(f"{os.path.dirname(__file__)}/chia-blockchain-gui/packages/gui/package.json")
