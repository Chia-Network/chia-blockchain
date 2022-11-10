from __future__ import annotations

import os
import pathlib
import platform
import subprocess
import sys
import tempfile

excepted_packages = {
    "keyrings.cryptfile",  # pure python
    "dnslib",  # pure python
}


def excepted(path: pathlib.Path) -> bool:
    # TODO: This should be implemented with a real file name parser though i'm
    #       uncertain at the moment what package that would be.

    name, dash, rest = path.name.partition("-")
    return name in excepted_packages


def main() -> int:
    with tempfile.TemporaryDirectory() as directory_string:
        print(f"Working in: {directory_string}")
        print()
        directory_path = pathlib.Path(directory_string)

        extras = ["upnp"]
        package_path_string = os.fspath(pathlib.Path(__file__).parent.parent)

        if len(extras) > 0:
            package_and_extras = f"{package_path_string}[{','.join(extras)}]"
        else:
            package_and_extras = package_path_string

        print("Downloading packages for Python version:")
        lines = [
            *sys.version.splitlines(),
            "",
            f"machine: {platform.machine()}",
            f"platform: {platform.platform()}",
        ]
        for line in lines:
            print(f"    {line}")
        print(flush=True)

        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--dest",
                os.fspath(directory_path),
                "--extra-index",
                "https://pypi.chia.net/simple/",
                package_and_extras,
            ],
            check=True,
        )

        failed_artifacts = []

        for artifact in directory_path.iterdir():
            if artifact.suffix == ".whl":
                # everything being a wheel is the target
                continue

            if excepted(artifact):
                continue

            failed_artifacts.append(artifact)

        if len(failed_artifacts) > 0:
            print("The following unacceptable artifacts were downloaded by pip:")
            for artifact in failed_artifacts:
                print(f"    {artifact.name}")

            return 1

        return 0


sys.exit(main())
