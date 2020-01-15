#!/usr/bin/python3
from setuptools import setup

dependencies = [
    "aiter",            # Used for async generator tools
    "blspy",            # Signature library
    "cbor2",            # Used for network wire format
    "pyyaml",           # Used for config file format
    "asyncssh",         # Used for SSH server for UI
    "miniupnpc",        # Allows users to open ports on their router
    "uvloop",           # Faster replacement to asyncio
    "aiosqlite",        # asyncio wrapper for sqlite, to store blocks
    "aiohttp",          # HTTP server for full node rpc
    "setuptools-scm",   # Used for versioning
    "setproctitle",     # Used to change the name of the process for ps, etc.
    "prompt-toolkit",   # Used to create a terminal based UI for full node
    "colorlog"          # Adds color to logs
]
dev_dependencies = [
    "pytest",
    "flake8",
    "mypy",
    "isort",
    "autoflake",
    "black",
    "pytest-asyncio"
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
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    zip_safe=False,
)
