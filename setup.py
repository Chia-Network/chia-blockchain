from setuptools import setup

dependencies = [
    "multidict==5.1.0",  # Avoid 5.2.0 due to Avast
    "aiofiles==0.7.0",  # Async IO for files
    "blspy==1.0.9",  # Signature library
    "chiavdf==1.0.5",  # timelord and vdf verification
    "chiabip158==1.1",  # bip158-style wallet filters
    "chiapos==1.0.9",  # proof of space
    "clvm==0.9.7",
    "clvm_tools==0.4.3",  # Currying, Program.to, other conveniences
    "clvm_rs==0.1.19",
    "clvm-tools-rs==0.1.7",  # Rust implementation of clvm_tools
    "aiohttp==3.7.4",  # HTTP server for full node rpc
    "aiosqlite==0.17.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.9",  # Binary data management library
    "colorama==0.4.4",  # Colorizes terminal output
    "colorlog==6.6.0",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    "cryptography==3.4.7",  # Python cryptography library for TLS - keyring conflict
    "fasteners==0.16.3",  # For interprocess file locking, expected to be replaced by filelock
    "filelock==3.4.2",  # For reading and writing config multiprocess and multithread safely  (non-reentrant locks)
    "keyring==23.0.1",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    #  "keyrings.cryptfile==1.3.8",  # Secure storage for keys on Linux (Will be replaced)
    #  See https://github.com/frispete/keyrings.cryptfile/issues/15
    "PyYAML==5.4.1",  # Used for config file format
    "setproctitle==1.2.2",  # Gives the chia processes readable names
    "sortedcontainers==2.4.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    # TODO: when moving to click 8 remove the pinning of black noted below
    "click==7.1.2",  # For the CLI
    "dnspythonchia==2.2.0",  # Query DNS seeds
    "watchdog==2.1.6",  # Filesystem event watching - watches keyring.yaml
    "dnslib==0.9.17",  # dns lib
    "typing-extensions==4.0.1",  # typing backports like Protocol and TypedDict
    "zstd==1.5.0.4",
    "packaging==21.0",
]

upnp_dependencies = [
    "miniupnpc==2.2.2",  # Allows users to open ports on their router
]

dev_dependencies = [
    "build",
    "pre-commit",
    "pytest",
    "pytest-asyncio>=0.18.1",  # require attribute 'fixture'
    "pytest-monitor; sys_platform == 'linux'",
    "pytest-xdist",
    "twine",
    "isort",
    "flake8",
    "mypy",
    # TODO: black 22.1.0 requires click>=8, remove this pin after updating to click 8
    "black==21.12b0",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "types-aiofiles",
    "types-click",
    "types-cryptography",
    "types-pkg_resources",
    "types-pyyaml",
    "types-setuptools",
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
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "chia",
        "chia.cmds",
        "chia.clvm",
        "chia.consensus",
        "chia.daemon",
        "chia.full_node",
        "chia.timelord",
        "chia.farmer",
        "chia.harvester",
        "chia.introducer",
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
        "chia.wallet.puzzles",
        "chia.wallet.rl_wallet",
        "chia.wallet.cat_wallet",
        "chia.wallet.did_wallet",
        "chia.wallet.settings",
        "chia.wallet.trading",
        "chia.wallet.util",
        "chia.ssl",
        "mozilla-ca",
    ],
    entry_points={
        "console_scripts": [
            "chia = chia.cmds.chia:main",
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
)


if __name__ == "__main__":
    setup(**kwargs)  # type: ignore
