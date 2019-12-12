#!/usr/bin/python3
from setuptools import setup

dependencies = ["blspy", "cbor2", "pyyaml", "asyncssh", "motor", "miniupnpc", "uvloop"]
dev_dependencies = [
    "pytest",
    "flake8",
    "mypy",
    "isort",
    "autoflake",
    "black",
    "pytest-asyncio",
]

setup(
    name="chiablockchain",
    author="Mariano Sorgente",
    author_email="mariano@chia.net",
    description="Chia proof of space plotting, proving, and verifying (wraps C++)",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="chia blockchain node",
    install_requires=dependencies + dev_dependencies,
    setup_requires=["setuptools_scm"],
    use_scm_version=True,
    long_description=open("README.md").read(),
    zip_safe=False,
)
