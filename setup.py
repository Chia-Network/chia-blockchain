from setuptools import setup

SETPROCTITLE_GITHUB = (
    "setproctitle @ "
    "https://github.com/Chia-Network/py-setproctitle/tarball/"
    "d2ed86c5080bb645d8f6b782a4a86706c860d9e6#egg=setproctitle-50.0.0"
)

CLVM_TOOLS_GITHUB = (
    "clvm-tools @ "
    "https://github.com/Chia-Network/clvm_tools/tarball/6ff53bcfeb0c970647b6cfdde360d32b316b1326#egg=clvm-tools"
)


dependencies = [
    "aiter==0.13.20191203",  # Used for async generator tools
    "blspy==0.1.14",  # Signature library
    "cbor2==5.0.1",  # Used for network wire format
    "clvm==0.4",  # contract language
    "PyYAML==5.3",  # Used for config file format
    "miniupnpc==2.0.2",  # Allows users to open ports on their router
    "aiosqlite==0.11.0",  # asyncio wrapper for sqlite, to store blocks
    "aiohttp==3.6.2",  # HTTP server for full node rpc
    "colorlog==4.1.0",  # Adds color to logs
    "chiavdf==0.12.1",  # timelord and vdf verification
    "chiabip158==0.12",  # bip158-style wallet filters
    "chiapos==0.12.2",  # proof of space
    "sortedcontainers==2.1.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    SETPROCTITLE_GITHUB,  # custom internal version of setproctitle, this should go away
    CLVM_TOOLS_GITHUB,  # clvm compiler tools
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

setup(
    name="chiablockchain",
    author="Mariano Sorgente",
    author_email="mariano@chia.net",
    description="Chia proof of space plotting, proving, and verifying (wraps C++)",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="chia blockchain node",
    install_requires=dependencies,
    setup_requires=["setuptools_scm"],
    extras_require=dict(uvloop=["uvloop"], dev=dev_dependencies),
    packages=[
        "src",
        "src.cmds",
        "src.consensus",
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
        "src.wallet.util",
    ],
    entry_points={
        "console_scripts": [
            "chia = src.cmds.cli:main",
            "chia-check-plots = src.cmds.check_plots:main",
            "chia-create-plots = src.cmds.create_plots:main",
            "chia-generate-keys = src.cmds.generate_keys:main",
            "chia-websocket-server = src.wallet.websocket_server:main",
        ]
    },
    package_data={
        "src.util": ["initial-*.yaml"],
        "src.server": ["dummy.crt", "dummy.key"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    zip_safe=False,
)
