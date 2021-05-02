from pkg_resources import DistributionNotFound, get_distribution, resource_filename
import subprocess

try:
    __version__= subprocess.run(["git", "describe", "--tags"], capture_output=True).stdout.decode('UTF-8').replace("\n", "")
except DistributionNotFound:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")
