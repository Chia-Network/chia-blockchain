import multiprocessing

from pkg_resources import DistributionNotFound, get_distribution, resource_filename

start_method = "spawn"
try:
    multiprocessing.set_start_method(start_method)
except RuntimeError:
    if multiprocessing.get_start_method(allow_none=True) != start_method:
        raise

try:
    __version__ = get_distribution("chia-blockchain").version
except DistributionNotFound:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")
