from __future__ import annotations

import os
import sys

from setuptools import setup

dependencies = [
    "aiofiles==22.1.0",  # Async IO for files
    "blspy==1.0.16",  # Signature library
    "chiavdf==1.0.8",  # timelord and vdf verification
    "chiabip158==1.2",  # bip158-style wallet filters
    "chiapos==1.0.11",  # proof of space
    "clvm==0.9.7",
    "clvm_tools==0.4.6",  # Currying, Program.to, other conveniences
    "chia_rs==0.2.0",
    "clvm-tools-rs==0.1.30",  # Rust implementation of clvm_tools' compiler
    "aiohttp==3.8.3",  # HTTP server for full node rpc
    "aiosqlite==0.17.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.9",  # Binary data management library
    "colorama==0.4.5",  # Colorizes terminal output
    "colorlog==6.7.0",  # Adds color to logs
    "concurrent-log-handler==0.9.20",  # Concurrently log and rotate logs
    "cryptography==38.0.3",  # Python cryptography library for TLS - keyring conflict
    "filelock==3.8.0",  # For reading and writing config multiprocess and multithread safely  (non-reentrant locks)
    "keyring==23.9.3",  # Store keys in MacOS Keychain, Windows Credential Locker
    "PyYAML==6.0",  # Used for config file format
    "setproctitle==1.2.3",  # Gives the chia processes readable names
    "sortedcontainers==2.4.0",  # For maintaining sorted mempools
    "click==8.1.3",  # For the CLI
    "dnspython==2.2.1",  # Query DNS seeds
    "watchdog==2.2.0",  # Filesystem event watching - watches keyring.yaml
    "dnslib==0.9.23",  # dns lib
    "typing-extensions==4.4.0",  # typing backports like Protocol and TypedDict
    "zstd==1.5.2.6",
    "packaging==21.3",
    "psutil==5.9.4",
]

upnp_dependencies = [
    "miniupnpc==2.2.2",  # Allows users to open ports on their router
]

dev_dependencies = [
    "anyio",
    "build",
    "coverage",
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
    # TODO: remove this pin after fixing the new complaints
    "mypy<1",
    "black==22.10.0",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "pyinstaller==5.6.2",
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
    python_requires=">=3.7, <4",
    keywords="chia blockchain node",
    install_requires=dependencies,
    extras_require=dict(
        dev=dev_dependencies,
        upnp=upnp_dependencies,
        legacy_keyring=legacy_keyring_dependencies,
    ),
    packages=[
        "build_scripts",
        "chia",
        "chia.cmds",
        "chia.clvm",
        "chia.consensus",
        "chia.daemon",
        "chia.data_layer",
        "chia.full_node",
        "chia.timelord",
        "chia.farmer",
        "chia.harvester",
        "chia.introducer",
        "chia.plot_sync",
        "chia.plotters",
        "chia.plotting",
        "chia.pools",
        "chia.protocols",
        "chia.rpc",
        "chia.seeder",
        "chia.server",
        "chia.simulator",
        "chia.types.blockchain_format",
        "chia.types",
        "chia.util",
        "chia.wallet",
        "chia.wallet.db_wallet",
        "chia.wallet.puzzles",
        "chia.wallet.cat_wallet",
        "chia.wallet.did_wallet",
        "chia.wallet.nft_wallet",
        "chia.wallet.settings",
        "chia.wallet.trading",
        "chia.wallet.util",
        "chia.ssl",
        "mozilla-ca",
    ],
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
        ]
    },
    package_data={
        "chia": ["pyinstaller.spec"],
        "": ["*.clvm", "*.clvm.hex", "*.clib", "*.clinc", "*.clsp", "py.typed"],
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
