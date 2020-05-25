from setuptools import setup


dependencies = [
    "aiter==0.13.20191203",  # Used for async generator tools
    "blspy==0.1.27",  # Signature library
    "cbor2==5.1.0",  # Used for network wire format
    "clvm==0.4",  # contract language
    "PyYAML==5.3.1",  # Used for config file format
    "aiosqlite==0.13.0",  # asyncio wrapper for sqlite, to store blocks
    "aiohttp==3.6.2",  # HTTP server for full node rpc
    "colorlog==4.1.0",  # Adds color to logs
    "chiavdf==0.12.16",  # timelord and vdf verification
    "chiabip158==0.14",  # bip158-style wallet filters
    "chiapos==0.12.18",  # proof of space
    "sortedcontainers==2.1.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    "clvm-tools==0.1.1",  # clvm compiler tools
    "bitstring==3.1.6",
    "keyring==21.2.1",
    "keyring_jeepney==0.2",
    "keyrings.cryptfile==1.3.4",
    "cryptography==2.9.2", #Python cryptography library for TLS
]

upnp_dependencies = [
    "miniupnpc==2.1",  # Allows users to open ports on their router
]
dev_dependencies = [
    "pytest",
    "flake8",
    "mypy",
    "isort",
    "autoflake",
    "black",
    "pytest-asyncio",
]

kwargs = dict(
    name="chia-blockchain",
    author="Mariano Sorgente",
    author_email="mariano@chia.net",
    description="Chia proof of space plotting, proving, and verifying (wraps C++)",
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
            "chia-check-plots = src.cmds.check_plots:main",
            "chia-create-plots = src.cmds.create_plots:main",
            "chia-wallet = src.wallet.websocket_server:main",
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
