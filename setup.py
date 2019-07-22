#!/usr/bin/python3
from setuptools import setup

dependencies = ['pytest', 'flake8', 'blspy==0.1.9']

setup(
    name='chiablockchain',
    version='0.1.1',
    author='Mariano Sorgente',
    author_email='mariano@chia.net',
    description='Chia proof of space plotting, proving, and verifying (wraps C++)',
    license='Apache License',
    python_requires='>=3.7',
    keywords='chia blockchain node',
    install_requires=dependencies,
    long_description=open('README.md').read(),
    zip_safe=False,
)
