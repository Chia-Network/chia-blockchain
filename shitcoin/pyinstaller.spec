# -*- mode: python ; coding: utf-8 -*-
import importlib
import pathlib
import platform

from pkg_resources import get_distribution

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

THIS_IS_WINDOWS = platform.system().lower().startswith("win")
THIS_IS_MAC = platform.system().lower().startswith("darwin")

ROOT = pathlib.Path(importlib.import_module("shitcoin").__file__).absolute().parent.parent


def solve_name_collision_problem(analysis):
    """
    There is a collision between the `shitcoin` file name (which is the executable)
    and the `shitcoin` directory, which contains non-code resources like `english.txt`.
    We move all the resources in the zipped area so there is no
    need to create the `shitcoin` directory, since the names collide.

    Fetching data now requires going into a zip file, so it will be slower.
    It's best if files that are used frequently are cached.

    A sample large compressible file (1 MB of `/dev/zero`), seems to be
    about eight times slower.

    Note that this hack isn't documented, but seems to work.
    """

    zipped = []
    datas = []
    for data in analysis.datas:
        if str(data[0]).startswith("shitcoin/"):
            zipped.append(data)
        else:
            datas.append(data)

    # items in this field are included in the binary
    analysis.zipped_data = zipped

    # these items will be dropped in the root folder uncompressed
    analysis.datas = datas


keyring_imports = collect_submodules("keyring.backends")

# keyring uses entrypoints to read keyring.backends from metadata file entry_points.txt.
keyring_datas = copy_metadata("keyring")[0]

version_data = copy_metadata(get_distribution("shitcoin-blockchain"))[0]

block_cipher = None

SERVERS = [
    "wallet",
    "full_node",
    "harvester",
    "farmer",
    "introducer",
    "timelord",
]

# TODO: collapse all these entry points into one `shitcoin_exec` entrypoint that accepts the server as a parameter

entry_points = ["shitcoin.cmds.shitcoin"] + [f"shitcoin.server.start_{s}" for s in SERVERS]

hiddenimports = []
hiddenimports.extend(entry_points)
hiddenimports.extend(keyring_imports)

binaries = [
    (
        f"{ROOT}/madmax/shitcoin_plot",
        "madmax"
    ),
    (
        f"{ROOT}/madmax/shitcoin_plot_k34",
        "madmax"
    )
]

if not THIS_IS_MAC:
    binaries.extend([
        (
            f"{ROOT}/bladebit/bladebit",
            "bladebit"
        )
    ])

if THIS_IS_WINDOWS:
    hiddenimports.extend(["win32timezone", "win32cred", "pywintypes", "win32ctypes.pywin32"])

# this probably isn't necessary
if THIS_IS_WINDOWS:
    entry_points.extend(["aiohttp", "shitcoin.util.bip39"])

if THIS_IS_WINDOWS:
    shitcoin_mod = importlib.import_module("shitcoin")
    dll_paths = ROOT / "*.dll"

    binaries = [
        (
            dll_paths,
            ".",
        ),
        (
            "C:\\Windows\\System32\\msvcp140.dll",
            ".",
        ),
        (
            "C:\\Windows\\System32\\vcruntime140_1.dll",
            ".",
        ),
        (
            f"{ROOT}\\madmax\\shitcoin_plot.exe",
            "madmax"
        ),
        (
            f"{ROOT}\\madmax\\shitcoin_plot_k34.exe",
            "madmax"
        ),
        (
            f"{ROOT}\\bladebit\\bladebit.exe",
            "bladebit"
        ),
    ]


datas = []

datas.append((f"{ROOT}/shitcoin/util/english.txt", "shitcoin/util"))
datas.append((f"{ROOT}/shitcoin/util/initial-config.yaml", "shitcoin/util"))
datas.append((f"{ROOT}/shitcoin/wallet/puzzles/*.hex", "shitcoin/wallet/puzzles"))
datas.append((f"{ROOT}/shitcoin/ssl/*", "shitcoin/ssl"))
datas.append((f"{ROOT}/mozilla-ca/*", "mozilla-ca"))
datas.append(version_data)

pathex = []


def add_binary(name, path_to_script, collect_args):
    analysis = Analysis(
        [path_to_script],
        pathex=pathex,
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        runtime_hooks=[],
        excludes=[],
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )

    solve_name_collision_problem(analysis)

    binary_pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

    binary_exe = EXE(
        binary_pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
    )

    collect_args.extend(
        [
            binary_exe,
            analysis.binaries,
            analysis.zipfiles,
            analysis.datas,
        ]
    )


COLLECT_ARGS = []

add_binary("shitcoin", f"{ROOT}/shitcoin/cmds/shitcoin.py", COLLECT_ARGS)
add_binary("daemon", f"{ROOT}/shitcoin/daemon/server.py", COLLECT_ARGS)

for server in SERVERS:
    add_binary(f"start_{server}", f"{ROOT}/shitcoin/server/start_{server}.py", COLLECT_ARGS)

COLLECT_KWARGS = dict(
    strip=False,
    upx_exclude=[],
    name="daemon",
)

coll = COLLECT(*COLLECT_ARGS, **COLLECT_KWARGS)
