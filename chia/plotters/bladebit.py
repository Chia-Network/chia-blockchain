import subprocess
import os
import sys


def install_bladebit(root_path):
    if sys.platform.startswith("linux"):
        print("Installing dependencies.")
        try:
            subprocess.run(
                [
                    "sudo",
                    "apt",
                    "install",
                    "-y",
                    "build-essential",
                    "cmake",
                    "libnuma-dev",
                    "git",
                ]
            )
        except Exception:
            raise ValueError("Could not install dependencies.")

        print("Cloning repository and its submodules.")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--recursive",
                    "https://github.com/harold-b/bladebit.git",
                ],
                cwd=str(root_path),
            )
        except Exception:
            raise ValueError("Could not clone bladebit repository.")

        bladebit_path = str(root_path) + "/bladebit"
        print("Building BLS library.")
        # Build bls library. Only needs to be done once.
        try:
            subprocess.run(["./build-bls"], cwd=bladebit_path)
        except Exception as e:
            raise ValueError(f"Building BLS library failed. {e}")

        print("Build bladebit.")
        try:
            subprocess.run(["make", "clean"], cwd=bladebit_path)
            subprocess.run(["make"], cwd=bladebit_path)
        except Exception as e:
            raise ValueError(f"Building bladebit failed. {e}")
    else:
        raise ValueError("Platform not supported yet for bladebit plotter.")


def plot_bladebit(args, root_path):
    if not os.path.exists(root_path / "bladebit/.bin/release/bladebit"):
        print("Installing bladebit plotter.")
        try:
            install_bladebit(root_path)
        except Exception as e:
            print(f"Exception while installing madmax plotter: {e}")
            return
    call_args = []
    call_args.append(str(root_path) + "/bladebit/.bin/release/bladebit")
    call_args.append("-t")
    call_args.append(str(args.threads))
    call_args.append("-n")
    call_args.append(str(args.count))
    call_args.append("-f")
    call_args.append(args.farmerkey.hex())
    if args.pool_key != b"":
        call_args.append("-p")
        call_args.append(args.pool_key.hex())
    if args.contract != "":
        call_args.append("-c")
        call_args.append(args.contract)
    if args.warmstart:
        call_args.append("-w")
    if args.id != b"":
        call_args.append("-i")
        call_args.append(args.id.hex())
    if args.verbose:
        call_args.append("-v")
    if args.nonuma:
        call_args.append("-m")
    call_args.append(args.outdir)
    try:
        subprocess.run(call_args)
    except Exception as e:
        print(f"Exception while plotting: {e} {type(e)}")
