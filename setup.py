from setuptools import setup

dependencies = [
    "multidict==5.1.0",  # Avoid 5.2.0 due to Avast
    "aiofiles==0.7.0",  # Async IO for files
    "blspy==1.0.9",  # Signature library
    "chiavdf==1.0.5",  # timelord and vdf verification
    "chiabip158==1.1",  # bip158-style wallet filters
    "chiapos==1.0.8",  # proof of space
    "clvm==0.9.7",
    "clvm_rs==0.1.17",
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
    "setproctitle==1.2.2",  # Gives the chinilla processes readable names
    "sortedcontainers==2.4.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
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
    "pre-commit",
    "pytest",
    "pytest-asyncio",
    "pytest-monitor; sys_platform == 'linux'",
    "pytest-xdist",
    "flake8",
    "mypy",
    "black",
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
    name="chinilla-blockchain",
    author="Edward Teach",
    author_email="edward@chinilla.com",
    description="Chinilla blockchain full node, farmer, timelord, and wallet.",
    url="https://chinilla.com/",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="chinilla blockchain node",
    install_requires=dependencies,
    setup_requires=["setuptools_scm"],
    extras_require=dict(
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "chinilla",
        "chinilla.cmds",
        "chinilla.clvm",
        "chinilla.consensus",
        "chinilla.daemon",
        "chinilla.full_node",
        "chinilla.timelord",
        "chinilla.farmer",
        "chinilla.harvester",
        "chinilla.introducer",
        "chinilla.plotters",
        "chinilla.plotting",
        "chinilla.pools",
        "chinilla.protocols",
        "chinilla.rpc",
        "chinilla.seeder",
        "chinilla.seeder.util",
        "chinilla.server",
        "chinilla.simulator",
        "chinilla.types.blockchain_format",
        "chinilla.types",
        "chinilla.util",
        "chinilla.wallet",
        "chinilla.wallet.puzzles",
        "chinilla.wallet.rl_wallet",
        "chinilla.wallet.cat_wallet",
        "chinilla.wallet.did_wallet",
        "chinilla.wallet.settings",
        "chinilla.wallet.trading",
        "chinilla.wallet.util",
        "chinilla.ssl",
        "mozilla-ca",
    ],
    entry_points={
        "console_scripts": [
            "chinilla = chinilla.cmds.chinilla:main",
            "chinilla_wallet = chinilla.server.start_wallet:main",
            "chinilla_full_node = chinilla.server.start_full_node:main",
            "chinilla_harvester = chinilla.server.start_harvester:main",
            "chinilla_farmer = chinilla.server.start_farmer:main",
            "chinilla_introducer = chinilla.server.start_introducer:main",
            "chinilla_seeder = chinilla.cmds.seeder:main",
            "chinilla_seeder_crawler = chinilla.seeder.start_crawler:main",
            "chinilla_seeder_server = chinilla.seeder.dns_server:main",
            "chinilla_timelord = chinilla.server.start_timelord:main",
            "chinilla_timelord_launcher = chinilla.timelord.timelord_launcher:main",
            "chinilla_full_node_simulator = chinilla.simulator.start_simulator:main",
        ]
    },
    package_data={
        "chinilla": ["pyinstaller.spec"],
        "": ["*.clvm", "*.clvm.hex", "*.clib", "*.clinc", "*.clsp", "py.typed"],
        "chinilla.util": ["initial-*.yaml", "english.txt"],
        "chinilla.ssl": ["chinilla_ca.crt", "chinilla_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)  # type: ignore
