"Import a package and install it with PIP if it doesn't exist."

import subprocess
import sys


def pip_import(module, pypi_name=None):
    """
    Return None if we can't import or install it.
    """
    try:
        return __import__(module)
    except ImportError:
        pass

    subprocess.call([sys.executable, "-m", "pip", "install", pypi_name or module])
    return __import__(module)
