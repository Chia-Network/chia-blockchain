import os
import pathlib
import subprocess
import sys
import tempfile

excepted_packages = {
    # "chia_blockchain",
    "keyrings.cryptfile",
    "dnslib",
}


def excepted(path: pathlib.Path) -> bool:
    # TODO: This should be implemented with a real file name parser though i'm
    #       uncertain at the moment what package that would be.

    name, dash, rest = path.name.partition("-")
    return name in excepted_packages
    # return any(path.name.startswith(f"{package_name}-") for package_name in excepted_packages)


def main() -> int:
    with tempfile.TemporaryDirectory() as directory_string:
        directory_path = pathlib.Path(directory_string)

        extras = ["upnp"]
        package = "."

        if len(extras) > 0:
            package_and_extras = f"{package}[{','.join(extras)}]"
        else:
            package_and_extras = package

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
