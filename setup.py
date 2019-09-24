#!/usr/bin/python3
from setuptools import setup

dependencies = ['blspy', 'cbor2', 'pyyaml']
dev_dependencies = ['pytest', 'flake8', 'ipython']

setup(
    name='chiablockchain',
    version='0.1.2',
    author='Mariano Sorgente',
    author_email='mariano@chia.net',
    description='Chia proof of space plotting, proving, and verifying (wraps C++)',
    license='Apache License',
    python_requires='>=3.7',
    keywords='chia blockchain node',
    install_requires=dependencies + dev_dependencies,
    long_description=open('README.md').read(),
    zip_safe=False,
)
