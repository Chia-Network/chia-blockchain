#!/usr/bin/env python
"""
setproctitle setup script.

Copyright (c) 2009-2016 Daniele Varrazzo <daniele.varrazzo@gmail.com>
"""

import os
import re
import sys

try:
    from setuptools import setup, Extension
except ImportError:
    from distutils.core import setup, Extension


VERSION = '1.1.10'


define_macros = {}

define_macros['SPT_VERSION'] = VERSION

if sys.platform.startswith('linux'):
    try:
        linux_version = list(map(int,
            re.search("[.0-9]+", os.popen("uname -r").read())
            .group().split(".")[:3]))
    except:
        pass
    else:
        if linux_version >= [2, 6, 9]:
            define_macros['HAVE_SYS_PRCTL_H'] = 1

elif sys.platform == 'darwin':
    # __darwin__ symbol is not defined; __APPLE__ is instead.
    define_macros['__darwin__'] = 1

elif 'bsd' in sys.platform:     # OMG, how many of them are?
    # Old BSD versions don't have setproctitle
    # TODO: not tested on an "old BSD"
    if 0 == os.spawnlp(os.P_WAIT, 'grep',
            'grep', '-q', 'setproctitle', '/usr/include/unistd.h', '/usr/include/stdlib.h'):
        define_macros['HAVE_SETPROCTITLE'] = 1
    else:
        define_macros['HAVE_PS_STRING'] = 1

# NOTE: the module may work on HP-UX using pstat
# thus setting define_macros['HAVE_SYS_PSTAT_H']
# see http://www.noc.utoronto.ca/~mikep/unix/HPTRICKS
# But I have none handy to test with.

mod_spt = Extension('setproctitle',
    define_macros=list(define_macros.items()),
    sources=[
        'src/setproctitle.c',
        'src/spt_debug.c',
        'src/spt_setup.c',
        'src/spt_status.c',
        'src/spt_strlcpy.c',
    ])

# patch distutils if it can't cope with the "classifiers" or
# "download_url" keywords
if sys.version < '2.2.3':
    from distutils.dist import DistributionMetadata
    DistributionMetadata.classifiers = None
    DistributionMetadata.download_url = None

# Try to include the long description in the setup
kwargs = {}
try:
    kwargs['long_description'] = (
        open('README.rst').read() +
        '\n' +
        open('HISTORY.rst').read())
except:
    pass

setup(
    name='setproctitle',
    description='A Python module to customize the process title',
    version=VERSION,
    author='Daniele Varrazzo',
    author_email='daniele.varrazzo@gmail.com',
    url='https://github.com/dvarrazzo/py-setproctitle',
    download_url='http://pypi.python.org/pypi/setproctitle/',
    license='BSD',
    platforms=['GNU/Linux', 'BSD', 'MacOS X', 'Windows'],
    classifiers=[r for r in map(str.strip, """
        Development Status :: 5 - Production/Stable
        Intended Audience :: Developers
        License :: OSI Approved :: BSD License
        Programming Language :: C
        Programming Language :: Python
        Programming Language :: Python :: 3
        Operating System :: POSIX :: Linux
        Operating System :: POSIX :: BSD
        Operating System :: MacOS :: MacOS X
        Operating System :: Microsoft :: Windows
        Topic :: Software Development
        """.splitlines()) if r],
    ext_modules=[mod_spt],
    **kwargs)
