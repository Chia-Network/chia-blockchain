# -*- mode: python ; coding: utf-8 -*-
import importlib
import os
import pathlib
import platform
import sysconfig

from pkg_resources import get_distribution

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

THIS_IS_WINDOWS = platform.system().lower().startswith("win")
THIS_IS_MAC = platform.system().lower().startswith("darwin")

ROOT = pathlib.Path(importlib.import_module("chia").__file__).absolute().parent.parent


def solve_name_collision_problem(analysis):
    """
    There is a collision between the `chia` file name (which is the executable)
    and the `chia` directory, which contains non-code resources like `english.txt`.
    We move all the resources in the zipped area so there is no
    need to create the `chia` directory, since the names collide.

    Fetching data now requires going into a zip file, so it will be slower.
    It's best if files that are used frequently are cached.

    A sample large compressible file (1 MB of `/dev/zero`), seems to be
    about eight times slower.

    Note that this hack isn't documented, but seems to work.
    """

    zipped = []
    datas = []
    for data in analysis.datas:
        if str(data[0]).startswith("chia/"):
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

version_data = copy_metadata(get_distribution("chia-blockchain"))[0]

block_cipher = None

SERVERS = [
    "data_layer",
    "wallet",
    "full_node",
    "harvester",
    "farmer",
    "introducer",
    "timelord",
]

if THIS_IS_WINDOWS:
    hidden_imports_for_windows = ["win32timezone", "win32cred", "pywintypes", "win32ctypes.pywin32"]
else:
    hidden_imports_for_windows = []

hiddenimports = [
    *collect_submodules("chia"),
    *keyring_imports,
    *hidden_imports_for_windows,
]

binaries = []

if os.path.exists(f"{ROOT}/madmax/chia_plot"):
    binaries.extend([
        (
            f"{ROOT}/madmax/chia_plot",
            "madmax"
        )
    ])

if os.path.exists(f"{ROOT}/madmax/chia_plot_k34",):
    binaries.extend([
        (
            f"{ROOT}/madmax/chia_plot_k34",
            "madmax"
        )
    ])

if os.path.exists(f"{ROOT}/bladebit/bladebit"):
    binaries.extend([
        (
            f"{ROOT}/bladebit/bladebit",
            "bladebit"
        )
    ])

if THIS_IS_WINDOWS:
    chia_mod = importlib.import_module("chia")
    dll_paths = pathlib.Path(sysconfig.get_path("platlib")) / "*.dll"

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
            f"{ROOT}\\madmax\\chia_plot.exe",
            "madmax"
        ),
        (
            f"{ROOT}\\madmax\\chia_plot_k34.exe",
            "madmax"
        ),
        (
            f"{ROOT}\\bladebit\\bladebit.exe",
            "bladebit"
        ),
    ]


datas = []

datas.append((f"{ROOT}/chia/util/english.txt", "chia/util"))
datas.append((f"{ROOT}/chia/util/initial-config.yaml", "chia/util"))
for path in sorted({path.parent for path in ROOT.joinpath("chia").rglob("*.hex")}):
    datas.append((f"{path}/*.hex", path.relative_to(ROOT)))
datas.append((f"{ROOT}/chia/ssl/*", "chia/ssl"))
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

add_binary("chia", f"{ROOT}/chia/cmds/chia.py", COLLECT_ARGS)
add_binary("daemon", f"{ROOT}/chia/daemon/server.py", COLLECT_ARGS)

for server in SERVERS:
    add_binary(f"start_{server}", f"{ROOT}/chia/server/start_{server}.py", COLLECT_ARGS)

add_binary("start_crawler", f"{ROOT}/chia/seeder/start_crawler.py", COLLECT_ARGS)
add_binary("start_seeder", f"{ROOT}/chia/seeder/dns_server.py", COLLECT_ARGS)
add_binary("start_data_layer_http", f"{ROOT}/chia/data_layer/data_layer_server.py", COLLECT_ARGS)
add_binary("start_data_layer_s3_plugin", f"{ROOT}/chia/data_layer/s3_plugin_service.py", COLLECT_ARGS)
add_binary("timelord_launcher", f"{ROOT}/chia/timelord/timelord_launcher.py", COLLECT_ARGS)

COLLECT_KWARGS = dict(
    strip=False,
    upx_exclude=[],
    name="daemon",
)

coll = COLLECT(*COLLECT_ARGS, **COLLECT_KWARGS)
