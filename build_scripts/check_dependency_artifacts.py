from __future__ import annotations

import os
import pathlib
import platform
import subprocess
import sys
import tempfile

# TODO: publish wheels for these
excepted_packages = {
    "dnslib",  # pure python
    "chialisp_loader",
    "chialisp_puzzles",
    "chia_base",
}


here = pathlib.Path(__file__).parent
project_root = here.parent


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
        artifact_directory_path = directory_path.joinpath("artifacts")
        artifact_directory_path.mkdir()

        extras = ["upnp"]

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

        requirements_path = directory_path.joinpath("exported_requirements.txt")

        if sys.platform == "win32":
            poetry_path = pathlib.Path(".penv/Scripts/poetry")
        else:
            poetry_path = pathlib.Path(".penv/bin/poetry")

        poetry_path = project_root.joinpath(poetry_path)

        subprocess.run(
            [
                os.fspath(poetry_path),
                "export",
                "--format",
                "requirements.txt",
                "--output",
                os.fspath(requirements_path),
                "--without-hashes",
                "--no-ansi",
                "--no-interaction",
                *(f"--extras={extra}" for extra in extras),
            ],
            check=True,
        )

        env = {key: value for key, value in os.environ.items() if key != "PIP_REQUIRE_VIRTUALENV"}

        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--dest",
                os.fspath(artifact_directory_path),
                "--extra-index",
                "https://pypi.chia.net/simple/",
                "--requirement",
                os.fspath(requirements_path),
            ],
            env=env,
            check=True,
        )

        failed_artifacts = []

        for artifact in artifact_directory_path.iterdir():
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
