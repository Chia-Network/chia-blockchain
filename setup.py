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
    "setproctitle==1.2.2",  # Gives the tad processes readable names
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
    name="chia-blockchain",
    author="Tad Developer",
    author_email="git@tadcoin.xyz",
    description="Tad blockchain full node, farmer, timelord, and wallet.",
    url="https://tadcoin.xyz/",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="tad blockchain node",
    install_requires=dependencies,
    setup_requires=["setuptools_scm"],
    extras_require=dict(
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "tad",
        "tad.cmds",
        "tad.clvm",
        "tad.consensus",
        "tad.daemon",
        "tad.full_node",
        "tad.timelord",
        "tad.farmer",
        "tad.harvester",
        "tad.introducer",
        "tad.plotting",
        "tad.pools",
        "tad.protocols",
        "tad.rpc",
        "tad.server",
        "tad.simulator",
        "tad.types.blockchain_format",
        "tad.types",
        "tad.util",
        "tad.wallet",
        "tad.wallet.puzzles",
        "tad.wallet.rl_wallet",
        "tad.wallet.cc_wallet",
        "tad.wallet.did_wallet",
        "tad.wallet.settings",
        "tad.wallet.trading",
        "tad.wallet.util",
        "tad.ssl",
        "mozilla-ca",
    ],
    entry_points={
        "console_scripts": [
            "tad = tad.cmds.tad:main",
            "tad_wallet = tad.server.start_wallet:main",
            "tad_full_node = tad.server.start_full_node:main",
            "tad_harvester = tad.server.start_harvester:main",
            "tad_farmer = tad.server.start_farmer:main",
            "tad_introducer = tad.server.start_introducer:main",
            "tad_timelord = tad.server.start_timelord:main",
            "tad_timelord_launcher = tad.timelord.timelord_launcher:main",
            "tad_full_node_simulator = tad.simulator.start_simulator:main",
        ]
    },
    package_data={
        "tad": ["pyinstaller.spec"],
        "tad.wallet.puzzles": ["*.clvm", "*.clvm.hex"],
        "tad.util": ["initial-*.yaml", "english.txt"],
        "tad.ssl": ["tad_ca.crt", "tad_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)
