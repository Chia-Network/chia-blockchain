from setuptools import setup

dependencies = [
    "aiter==0.13.20191203",  # Used for async generator tools
    "blspy==1.0",  # Signature library
    "chiavdf==1.0.1",  # timelord and vdf verification
    "chiabip158==1.0",  # bip158-style wallet filters
    "chiapos==0.9",  # proof of space
    "clvm==0.9.4",
    "clvm_rs==0.1.4",
    "clvm_tools==0.4.3",
    "aiohttp==3.7.4",  # HTTP server for full node rpc
    "aiosqlite==0.17.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.7",  # Binary data management library
    "colorlog==4.7.2",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    "cryptography==3.4.6",  # Python cryptography library for TLS - keyring conflict
    "keyring==23.0",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    #  "keyrings.cryptfile==1.3.8",  # Secure storage for keys on Linux (Will be replaced)
    #  See https://github.com/frispete/keyrings.cryptfile/issues/15
    "PyYAML==5.4.1",  # Used for config file format
    "setproctitle==1.2.2",  # Gives the chia processes readable names
    "sortedcontainers==2.3.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    "click==7.1.2",  # For the CLI
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
        "mozilla-ca",
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
        "src.ssl": ["chia_ca.crt", "chia_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)
