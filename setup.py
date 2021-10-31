from setuptools import setup

dependencies = [
    "blspy==1.0.6",  # Signature library
    "shitcoinvdf==1.0.3",  # timelord and vdf verification
    "shitcoinbip158==1.0",  # bip158-style wallet filters
    "shitcoinpos==1.0.6",  # proof of space
    "clvm==0.9.7",
    "clvm_rs==0.1.15",
    "clvm_tools==0.4.3",
    "aiohttp==3.7.4",  # HTTP server for full node rpc
    "aiosqlite==0.17.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.9",  # Binary data management library
    "colorama==0.4.4",  # Colorizes terminal output
    "colorlog==5.0.1",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    "cryptography==3.4.7",  # Python cryptography library for TLS - keyring conflict
    "fasteners==0.16.3",  # For interprocess file locking
    "keyring==23.0.1",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    #  "keyrings.cryptfile==1.3.8",  # Secure storage for keys on Linux (Will be replaced)
    #  See https://github.com/frispete/keyrings.cryptfile/issues/15
    "PyYAML==5.4.1",  # Used for config file format
    "setproctitle==1.2.2",  # Gives the shitcoin processes readable names
    "sortedcontainers==2.4.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    "click==7.1.2",  # For the CLI
    "dnspython==2.1.0",  # Query DNS seeds
    "watchdog==2.1.6",  # Filesystem event watching - watches keyring.yaml
]

upnp_dependencies = [
    "miniupnpc==2.2.2",  # Allows users to open ports on their router
]

dev_dependencies = [
    "pytest",
    "pytest-asyncio",
    "flake8",
    "mypy",
    "black",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "types-setuptools",
]

kwargs = dict(
    name="shitcoin-blockchain",
    author="Mariano Sorgente",
    author_email="mariano@shitcoin.net",
    description="shitcoin blockchain full node, farmer, timelord, and wallet.",
    url="https://shitcoin.net/",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="shitcoin blockchain node",
    install_requires=dependencies,
    setup_requires=["setuptools_scm"],
    extras_require=dict(
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "shitcoin",
        "shitcoin.cmds",
        "shitcoin.clvm",
        "shitcoin.consensus",
        "shitcoin.daemon",
        "shitcoin.full_node",
        "shitcoin.timelord",
        "shitcoin.farmer",
        "shitcoin.harvester",
        "shitcoin.introducer",
        "shitcoin.plotters",
        "shitcoin.plotting",
        "shitcoin.pools",
        "shitcoin.protocols",
        "shitcoin.rpc",
        "shitcoin.server",
        "shitcoin.simulator",
        "shitcoin.types.blockchain_format",
        "shitcoin.types",
        "shitcoin.util",
        "shitcoin.wallet",
        "shitcoin.wallet.puzzles",
        "shitcoin.wallet.rl_wallet",
        "shitcoin.wallet.cc_wallet",
        "shitcoin.wallet.did_wallet",
        "shitcoin.wallet.settings",
        "shitcoin.wallet.trading",
        "shitcoin.wallet.util",
        "shitcoin.ssl",
        "mozilla-ca",
    ],
    entry_points={
        "console_scripts": [
            "shitcoin = shitcoin.cmds.shitcoin:main",
            "shitcoin_wallet = shitcoin.server.start_wallet:main",
            "shitcoin_full_node = shitcoin.server.start_full_node:main",
            "shitcoin_harvester = shitcoin.server.start_harvester:main",
            "shitcoin_farmer = shitcoin.server.start_farmer:main",
            "shitcoin_introducer = shitcoin.server.start_introducer:main",
            "shitcoin_timelord = shitcoin.server.start_timelord:main",
            "shitcoin_timelord_launcher = shitcoin.timelord.timelord_launcher:main",
            "shitcoin_full_node_simulator = shitcoin.simulator.start_simulator:main",
        ]
    },
    package_data={
        "shitcoin": ["pyinstaller.spec"],
        "": ["*.clvm", "*.clvm.hex", "*.clib", "*.clinc", "*.clsp", "py.typed"],
        "shitcoin.util": ["initial-*.yaml", "english.txt"],
        "shitcoin.ssl": ["shitcoin_ca.crt", "shitcoin_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)  # type: ignore
