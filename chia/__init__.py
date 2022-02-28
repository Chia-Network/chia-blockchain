import multiprocessing

from pkg_resources import DistributionNotFound, get_distribution, resource_filename

# The default multiprocessing start method on Linux has resulted in various issues.
# Several have been around resources being inherited by the worker processes resulting
# in ports, files, or streams, being held open unexpectedly.  This can also affect
# memory used by the subprocesses and such.

start_method = "spawn"
try:
    # Set the start method.  This may already have been done by the test suite.
    multiprocessing.set_start_method(start_method)
except RuntimeError:
    # Setting can fail if it has already been done.  We do not care about the failure
    # if the start method is what we want it to be anyways.
    if multiprocessing.get_start_method(allow_none=True) != start_method:
        # The start method is not what we wanted.  We do not want to continue with
        # this without further consideration.
        raise

try:
    __version__ = get_distribution("chia-blockchain").version
except DistributionNotFound:
    # package is not installed
    __version__ = "unknown"

PYINSTALLER_SPEC_PATH = resource_filename("chia", "pyinstaller.spec")
