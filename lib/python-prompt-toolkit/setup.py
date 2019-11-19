#!/usr/bin/env python
import os
import re

from setuptools import find_packages, setup

with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as f:
    long_description = f.read()


def get_version(package):
    """
    Return package version as listed in `__version__` in `__init__.py`.
    """
    path = os.path.join(os.path.dirname(__file__), package, '__init__.py')
    with open(path, 'rb') as f:
        init_py = f.read().decode('utf-8')
    return re.search("__version__ = ['\"]([^'\"]+)['\"]", init_py).group(1)


setup(
    name='prompt_toolkit',
    author='Jonathan Slenders',
    version=get_version('prompt_toolkit'),
    url='https://github.com/prompt-toolkit/python-prompt-toolkit',
    description='Library for building powerful interactive command lines in Python',
    long_description=long_description,
    packages=find_packages('.'),
    install_requires=[
        'wcwidth',
    ],
    python_requires='>=3.6',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python',
        'Topic :: Software Development',
    ],
)
