from setuptools import setup


dependencies = [
    "aiter==0.13.20191203",  # Used for async generator tools
    "blspy==0.2c1",  # Signature library
    "chiavdf==0.12.21",  # timelord and vdf verification
    "chiabip158==0.15",  # bip158-style wallet filters
    "chiapos==0.12.23",  # proof of space
    "clvm==0.4",  # contract language
    "clvm-tools==0.1.1",  # clvm compiler tools
    "aiohttp==3.6.2",  # HTTP server for full node rpc
    "aiosqlite==0.13.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.7",  # Binary data management library
    "cbor2==5.1.0",  # Used for network wire format
    "colorlog==4.1.0",  # Adds color to logs
    "concurrent-log-handler==0.9.16",  # Concurrently log and rotate logs
    "cryptography==2.9.2", #Python cryptography library for TLS
    "keyring==21.2.1",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    "PyYAML==5.3.1",  # Used for config file format
    "sortedcontainers==2.2.2",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
]

upnp_dependencies = [
    "miniupnpc==2.1",  # Allows users to open ports on their router
]
dev_dependencies = [
    "pytest",
    "pytest-asyncio",
    "flake8",
    "mypy",
    "black",
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
    setup_requires=["setuptools_scm"],
    extras_require=dict(
        uvloop=["uvloop"], dev=dev_dependencies, upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "src",
        "src.cmds",
        "src.consensus",
        "src.daemon",
        "src.full_node",
        "src.protocols",
        "src.rpc",
        "src.server",
        "src.simulator",
        "src.types",
        "src.util",
        "src.wallet",
        "src.wallet.puzzles",
        "src.wallet.rl_wallet",
        "src.wallet.cc_wallet",
        "src.wallet.util",
        "src.wallet.trading",
        "src.ssl",
    ],
    scripts=[
        "scripts/_chia-common",
        "scripts/_chia-stop-wallet",
        "scripts/chia-drop-db",
        "scripts/chia-restart-harvester",
        "scripts/chia-start-sim",
        "scripts/chia-stop-all",
    ],
    entry_points={
        "console_scripts": [
            "chia = src.cmds.chia:main",
            "chia-wallet = src.server.start_wallet:main",
            "chia_full_node = src.server.start_full_node:main",
            "chia_harvester = src.server.start_harvester:main",
            "chia_farmer = src.server.start_farmer:main",
            "chia_introducer = src.server.start_introducer:main",
            "chia_timelord = src.server.start_timelord:main",
            "chia_timelord_launcher = src.timelord_launcher:main",
            "chia_full_node_simulator = src.simulator.start_simulator:main",
        ]
    },
    package_data={
        "src.util": ["initial-*.yaml", "english.txt"],
        "src.server": ["dummy.crt", "dummy.key"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)
