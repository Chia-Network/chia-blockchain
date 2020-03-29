from setuptools import setup

dependencies = [
    "aiter",  # Used for async generator tools
    "blspy",  # Signature library
    "cbor2",  # Used for network wire format
    "pyyaml",  # Used for config file format
    "miniupnpc",  # Allows users to open ports on their router
    "aiosqlite",  # asyncio wrapper for sqlite, to store blocks
    "aiohttp",  # HTTP server for full node rpc
    "setuptools-scm",  # Used for versioning
    "colorlog",  # Adds color to logs
    "chiavdf",  # timelord and vdf verification
    "chiabip158",  # bip158-style wallet filters
    "chiapos",  # proof of space
    "sortedcontainers",
    "websockets",
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
    extras_require={"uvloop": ["uvloop"], },
    packages=[
        "src",
        "src.cmds",
        "src.consensus",
        "src.full_node",
        "src.pool",
        "src.protocols",
        "src.rpc",
        "src.server",
        "src.simulator",
        "src.types",
        "src.types.hashable",
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
