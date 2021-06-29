from setuptools import setup

dependencies = [
    "blspy==1.0.2",  # Signature library
    "chiavdf==1.0.2",  # timelord and vdf verification
    "chiabip158==1.0",  # bip158-style wallet filters
    "chiapos==1.0.3",  # proof of space
    "clvm==0.9.7",
    "clvm_rs==0.1.8",
    "clvm_tools==0.4.3",
    "aiohttp==3.7.4",  # HTTP server for full node rpc
    "aiosqlite==0.17.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.7",  # Binary data management library
    "colorlog==5.0.1",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    "cryptography==3.4.7",  # Python cryptography library for TLS - keyring conflict
    "keyring==23.0.1",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    #  "keyrings.cryptfile==1.3.8",  # Secure storage for keys on Linux (Will be replaced)
    #  See https://github.com/frispete/keyrings.cryptfile/issues/15
    "PyYAML==5.4.1",  # Used for config file format
    "setproctitle==1.2.2",  # Gives the sector processes readable names
    "sortedcontainers==2.3.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    "click==7.1.2",  # For the CLI
    "dnspython==2.1.0",  # Query DNS seeds
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
]

kwargs = dict(
    name="sector-blockchain",
    author="Mariano Sorgente",
    author_email="mariano@chia.net",
    description="Chia blockchain full node, farmer, timelord, and wallet.",
    url="https://sectornetwork.world/",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="sector blockchain node",
    install_requires=dependencies,
    setup_requires=["setuptools_scm"],
    extras_require=dict(
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "sector",
        "sector.cmds",
        "sector.consensus",
        "sector.daemon",
        "sector.full_node",
        "sector.timelord",
        "sector.farmer",
        "sector.harvester",
        "sector.introducer",
        "sector.plotting",
        "sector.protocols",
        "sector.rpc",
        "sector.server",
        "sector.simulator",
        "sector.types.blockchain_format",
        "sector.types",
        "sector.util",
        "sector.wallet",
        "sector.wallet.puzzles",
        "sector.wallet.rl_wallet",
        "sector.wallet.cc_wallet",
        "sector.wallet.did_wallet",
        "sector.wallet.settings",
        "sector.wallet.trading",
        "sector.wallet.util",
        "sector.ssl",
        "mozilla-ca",
    ],
    entry_points={
        "console_scripts": [
            "sector = sector.cmds.sector:main",
            "sector_wallet = sector.server.start_wallet:main",
            "sector_full_node = sector.server.start_full_node:main",
            "sector_harvester = sector.server.start_harvester:main",
            "sector_farmer = sector.server.start_farmer:main",
            "sector_introducer = sector.server.start_introducer:main",
            "sector_timelord = sector.server.start_timelord:main",
            "sector_timelord_launcher = sector.timelord.timelord_launcher:main",
            "sector_full_node_simulator = sector.simulator.start_simulator:main",
        ]
    },
    package_data={
        "sector": ["pyinstaller.spec"],
        "sector.wallet.puzzles": ["*.clvm", "*.clvm.hex"],
        "sector.util": ["initial-*.yaml", "english.txt"],
        "sector.ssl": ["chia_ca.crt", "chia_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)
