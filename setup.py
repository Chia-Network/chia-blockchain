from __future__ import annotations

import os
import sys

from setuptools import find_packages, setup

dependencies = [
    "aiofiles==23.1.0",  # Async IO for files
    "anyio==3.7.0",
    "blspy==2.0.2",  # Signature library
    "boto3==1.26.161",  # AWS S3 for DL s3 plugin
    "chiavdf==1.0.9",  # timelord and vdf verification
    "chiabip158==1.2",  # bip158-style wallet filters
    "chiapos==2.0.0rc1",  # proof of space
    "clvm==0.9.7",
    "clvm_tools==0.4.6",  # Currying, Program.to, other conveniences
    "chia_rs==0.2.9",
    "clvm-tools-rs==0.1.34",  # Rust implementation of clvm_tools' compiler
    "aiohttp==3.8.4",  # HTTP server for full node rpc
    "aiosqlite==0.19.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==4.0.2",  # Binary data management library
    "colorama==0.4.6",  # Colorizes terminal output
    "colorlog==6.7.0",  # Adds color to logs
    "concurrent-log-handler==0.9.24",  # Concurrently log and rotate logs
    "cryptography==41.0.1",  # Python cryptography library for TLS - keyring conflict
    "filelock==3.12.2",  # For reading and writing config multiprocess and multithread safely  (non-reentrant locks)
    "keyring==23.13.1",  # Store keys in MacOS Keychain, Windows Credential Locker
    "PyYAML==6.0",  # Used for config file format
    "setproctitle==1.3.2",  # Gives the chia processes readable names
    "sortedcontainers==2.4.0",  # For maintaining sorted mempools
    "click==8.1.3",  # For the CLI
    "dnspython==2.3.0",  # Query DNS seeds
    "watchdog==2.2.0",  # Filesystem event watching - watches keyring.yaml
    "dnslib==0.9.23",  # dns lib
    "typing-extensions==4.6.3",  # typing backports like Protocol and TypedDict
    "zstd==1.5.5.1",
    "packaging==23.1",
    "psutil==5.9.4",
]

upnp_dependencies = [
    "miniupnpc==2.2.2",  # Allows users to open ports on their router
]

dev_dependencies = [
    "build",
    # >=7.2.4 for https://github.com/nedbat/coveragepy/issues/1604
    "coverage>=7.2.4",
    "diff-cover",
    "pre-commit",
    "py3createtorrent",
    "pylint",
    "pytest",
    "pytest-asyncio>=0.18.1",  # require attribute 'fixture'
    "pytest-cov",
    "pytest-monitor; sys_platform == 'linux'",
    "pytest-xdist",
    "twine",
    "isort",
    "flake8",
    "mypy",
    "black==23.3.0",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "pyinstaller==5.13.0",
    "types-aiofiles",
    "types-cryptography",
    "types-pkg_resources",
    "types-pyyaml",
    "types-setuptools",
]

legacy_keyring_dependencies = [
    "keyrings.cryptfile==1.3.9",
]

kwargs = dict(
    name="chia-blockchain",
    author="Mariano Sorgente",
    author_email="mariano@chia.net",
    description="Chia blockchain full node, farmer, timelord, and wallet.",
    url="https://chia.net/",
    license="Apache License",
    python_requires=">=3.8.1, <4",
    keywords="chia blockchain node",
    install_requires=dependencies,
    extras_require=dict(
        dev=dev_dependencies,
        upnp=upnp_dependencies,
        legacy_keyring=legacy_keyring_dependencies,
    ),
    packages=find_packages(include=["build_scripts", "chia", "chia.*", "mozilla-ca"]),
    entry_points={
        "console_scripts": [
            "chia = chia.cmds.chia:main",
            "chia_daemon = chia.daemon.server:main",
            "chia_wallet = chia.server.start_wallet:main",
            "chia_full_node = chia.server.start_full_node:main",
            "chia_harvester = chia.server.start_harvester:main",
            "chia_farmer = chia.server.start_farmer:main",
            "chia_introducer = chia.server.start_introducer:main",
            "chia_crawler = chia.seeder.start_crawler:main",
            "chia_seeder = chia.seeder.dns_server:main",
            "chia_timelord = chia.server.start_timelord:main",
            "chia_timelord_launcher = chia.timelord.timelord_launcher:main",
            "chia_full_node_simulator = chia.simulator.start_simulator:main",
            "chia_data_layer = chia.server.start_data_layer:main",
            "chia_data_layer_http = chia.data_layer.data_layer_server:main",
            "chia_data_layer_s3_plugin = chia.data_layer.s3_plugin_service:run_server",
        ]
    },
    package_data={
        "chia": ["pyinstaller.spec"],
        "": ["*.clsp", "*.clsp.hex", "*.clvm", "*.clib", "py.typed"],
        "chia.util": ["initial-*.yaml", "english.txt"],
        "chia.ssl": ["chia_ca.crt", "chia_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
    project_urls={
        "Source": "https://github.com/Chia-Network/chia-blockchain/",
        "Changelog": "https://github.com/Chia-Network/chia-blockchain/blob/main/CHANGELOG.md",
    },
)

if "setup_file" in sys.modules:
    # include dev deps in regular deps when run in snyk
    dependencies.extend(dev_dependencies)

if len(os.environ.get("CHIA_SKIP_SETUP", "")) < 1:
    setup(**kwargs)  # type: ignore
