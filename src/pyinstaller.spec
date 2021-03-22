# -*- mode: python ; coding: utf-8 -*-
import importlib
import pathlib
import platform

from pkg_resources import get_distribution

from os import listdir
from os.path import isfile, join
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

THIS_IS_WINDOWS = platform.system().lower().startswith("win")


def dir_for_module(mod_name):
    """
    This returns a path to a directory
    """
    mod = importlib.import_module(mod_name)
    return pathlib.Path(mod.__file__).parent


def path_for_file(mod_name, filename=None):
    """
    This returns a path to a file (__init__.py by default)
    """
    mod = importlib.import_module(mod_name)

    # some modules, like `chia.ssl` don't set mod.__file__ because there isn't actually
    # any code in there. We have to look at mod.__path__ instead, which is a list.
    # for now, we just take the first item, since this function isn't expected to
    # return a list of paths, just one path.
    # BRAIN DAMAGE

    if mod.__file__ is None:
        path = pathlib.Path(mod.__path__._path[0])
        if filename is None:
            raise ValueError("no file __init__.py in this module")
        return path / filename

    path = pathlib.Path(mod.__file__)
    if filename is not None:
        path = path.parent / filename
    return path


# Include all files that end with clvm.hex
puzzles_path = dir_for_module("chia.wallet.puzzles")

puzzle_dist_path = "./chia/wallet/puzzles"
onlyfiles = [f for f in listdir(puzzles_path) if isfile(join(puzzles_path, f))]

root = pathlib.Path().absolute()

keyring_imports = collect_submodules("keyring.backends")

# keyring uses entrypoints to read keyring.backends from metadata file entry_points.txt.
keyring_datas = copy_metadata("keyring")[0]

version_data = copy_metadata(get_distribution("chia-blockchain"))[0]

block_cipher = None

other = ["pkg_resources.py2_warn"]

SERVERS = [
    "wallet",
    "full_node",
    "harvester",
    "farmer",
    "introducer",
    "timelord",
]

if THIS_IS_WINDOWS:
    other.extend(["win32timezone", "win32cred", "pywintypes", "win32ctypes.pywin32"])

# TODO: collapse all these entry points into one `chia_exec` entrypoint that accepts the server as a parameter

entry_points = ["chia.cmds.chia"] + [f"chia.server.start_{s}" for s in SERVERS]


if THIS_IS_WINDOWS:
    # this probably isn't necessary
    entry_points.extend(["aiohttp", "chia.util.bip39"])

hiddenimports = []
hiddenimports.extend(other)
hiddenimports.extend(entry_points)
hiddenimports.extend(keyring_imports)

binaries = []
if THIS_IS_WINDOWS:
    binaries = [
        (
            dir_for_module("chia").parent / "*.dll",
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
    ]


datas = [
    (puzzles_path, puzzle_dist_path),
    (path_for_file("mozilla-ca", "cacert.pem"), f"./mozilla-ca/"),
    (path_for_file("chia.ssl", "dst_root_ca.pem"), f"./chia/ssl/"),
    (path_for_file("chia.ssl", "chia_ca.key"), f"./chia/ssl/"),
    (path_for_file("chia.ssl", "chia_ca.crt"), f"./chia/ssl/"),
    (path_for_file("chia.util", "english.txt"), f"./chia/util/"),
    version_data,
]


pathex = [root]

chia = Analysis(
    [path_for_file("chia.cmds.chia")],
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

chia_pyz = PYZ(chia.pure, chia.zipped_data, cipher=block_cipher)

chia_exe = EXE(
    chia_pyz,
    chia.scripts,
    [],
    exclude_binaries=True,
    name="chia",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
)


COLLECT_ARGS = [
    chia_exe,
    chia.binaries,
    chia.zipfiles,
    chia.datas,
]

for server in SERVERS:
    analysis = Analysis(
        [path_for_file(f"chia.server.start_{server}")],
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

    pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=f"start_{server}",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
    )

    COLLECT_ARGS.extend([exe, analysis.binaries, analysis.zipfiles, analysis.datas])

COLLECT_KWARGS = dict(
    strip=False,
    upx_exclude=[],
    name="daemon",
)

coll = COLLECT(*COLLECT_ARGS, **COLLECT_KWARGS)
