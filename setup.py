from setuptools import setup


dependencies = [
    "aiter==0.13.20191203",  # Used for async generator tools
    "blspy==0.3.5",  # Signature library
    "chiavdf==0.15.0",  # timelord and vdf verification
    "chiabip158==0.19",  # bip158-style wallet filters
    "chiapos==0.12.44",  # proof of space
    "clvm==0.8.9",
    "clvm_rs==0.1.3",  # noqa
    "clvm_tools==0.3.5",  # noqa
    "aiohttp==3.7.3",  # HTTP server for full node rpc
    "aiosqlite@git+https://github.com/mariano54/aiosqlite.git@47c7b21dd04adb1d41073ee9911a9d4b9c4b370f#egg=aiosqlite",
    # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.7",  # Binary data management library
    "colorlog==4.7.2",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    #  "cryptography==3.4.1",  # Python cryptography library for TLS - keyring conflict
    "cryptography==3.3.2",  # Python cryptography library for TLS
    "keyring==21.5.0",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    "PyYAML==5.4.1",  # Used for config file format
    "setproctitle==1.2.2",  # Gives the chia processes readable names
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
    package_data={"src.util": ["initial-*.yaml", "english.txt"], "src.ssl": ["chia_ca.crt", "chia_ca.key"]},
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)
