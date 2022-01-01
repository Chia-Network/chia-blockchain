import multiprocessing

from pkg_resources import DistributionNotFound, get_distribution, resource_filename

multiprocessing.set_start_method("spawn")

try:
    __version__ = get_distribution("chia-blockchain").version
except DistributionNotFound:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")
