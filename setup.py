from setuptools import setup


dependencies = [
    "aiter==0.13.20191203",  # Used for async generator tools
    "blspy==0.3.1",  # Signature library
    "chiavdf==0.13.2",  # timelord and vdf verification
    "chiabip158==0.17",  # bip158-style wallet filters
    "chiapos==0.12.41",  # proof of space
    "clvm==0.7",
    "clvm_tools==0.2.0",
    "aiohttp==3.7.3",  # HTTP server for full node rpc
    "aiosqlite@git+https://github.com/mariano54/aiosqlite.git@28cb5754deec562ac931da8fca799fb82df97a12#egg=aiosqlite",
    # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.7",  # Binary data management library
    "cbor2==5.2.0",  # Used for network wire format
    "colorlog==4.6.2",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    "cryptography==3.3.1",  # Python cryptography library for TLS
    "keyring==21.5.0",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    "PyYAML==5.3.1",  # Used for config file format
    "sortedcontainers==2.3.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
]

upnp_dependencies = [
    "miniupnpc==2.0.2",  # Allows users to open ports on their router
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
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "src",
        "src.cmds",
        "src.consensus",
        "src.daemon",
        "src.full_node",
        "src.timelord",
        "src.farmer",
        "src.harvester",
        "src.introducer",
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
    entry_points={
        "console_scripts": [
            "chia = src.cmds.chia:main",
            "chia_wallet = src.server.start_wallet:main",
            "chia_full_node = src.server.start_full_node:main",
            "chia_harvester = src.server.start_harvester:main",
            "chia_farmer = src.server.start_farmer:main",
            "chia_introducer = src.server.start_introducer:main",
            "chia_timelord = src.server.start_timelord:main",
            "chia_timelord_launcher = src.timelord.timelord_launcher:main",
            "chia_full_node_simulator = src.simulator.start_simulator:main",
        ]
    },
    package_data={
        "src.util": ["initial-*.yaml", "english.txt"],
        "src.server": ["dummy.crt", "dummy.key"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)
