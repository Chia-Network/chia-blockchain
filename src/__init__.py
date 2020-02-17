from setuptools_scm import get_version
try:
    __version__ = version = get_version()
except LookupError:
    pass
