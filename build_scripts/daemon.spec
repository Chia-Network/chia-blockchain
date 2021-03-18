# -*- mode: python ; coding: utf-8 -*-
import importlib
import pathlib

from pkg_resources import get_distribution

from os import listdir
from os.path import isfile, join
from PyInstaller.utils.hooks import copy_metadata


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

    # some modules, like `src.ssl` don't set mod.__file__ because there isn't actually
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
puzzles_path = dir_for_module("src.wallet.puzzles")

puzzle_dist_path = "./src/wallet/puzzles"
onlyfiles = [f for f in listdir(puzzles_path) if isfile(join(puzzles_path, f))]

hex_puzzles = []
for file in onlyfiles:
    if file.endswith("clvm.hex"):
        puzzle_path = f"{puzzles_path}/{file}"
        hex_puzzles.append((puzzles_path, puzzle_dist_path))

build = pathlib.Path().absolute()
root = build.parent

version_data = copy_metadata(get_distribution("chia-blockchain"))[0]

block_cipher = None

hiddenimports = []

other = ["aiter.active_aiter", "aiter.aiter_forker", "aiter.aiter_to_iter", "aiter.azip", "aiter.flatten_aiter", "aiter.gated_aiter",
"aiter.iter_to_aiter", "aiter.join_aiters", "aiter.map_aiter", "aiter.map_filter_aiter", "aiter.preload_aiter",
"aiter.push_aiter", "aiter.sharable_aiter", "aiter.stoppable_aiter", "pkg_resources.py2_warn"]

entry_points = ["src.cmds.chia",
            "src.server.start_wallet",
            "src.server.start_full_node",
            "src.server.start_harvester",
            "src.server.start_farmer",
            "src.server.start_introducer",
            "src.server.start_timelord",
            "src.timelord_launcher",
            "src.simulator.start_simulator"]

hiddenimports.extend(other)
hiddenimports.extend(entry_points)

daemon = Analysis([path_for_file("src.daemon.server")],
             pathex=[path_for_file("aiter"), f"{root}"],
             binaries = [],
             datas=[version_data, (path_for_file("src.util", "initial-config.yaml"), f"./src/util/"), ] +
             hex_puzzles,
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

full_node = Analysis([path_for_file("src.server.start_full_node")],
             pathex=[path_for_file("aiter"), f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

wallet = Analysis([path_for_file("src.server.start_wallet")],
             pathex=[path_for_file("aiter"), f"{root}"],
             binaries = [],
             datas=[
                (path_for_file("mozilla-ca", "cacert.pem"), f"./mozilla-ca/"),
                (path_for_file("src.ssl", "dst_root_ca.pem"), f"./src/ssl/"),
                (path_for_file("src.ssl", "chia_ca.key"), f"./src/ssl/"),
                (path_for_file("src.ssl", "chia_ca.crt"), f"./src/ssl/"),
                (path_for_file("src.util", "english.txt"), f"./src/util/"),
                version_data ] + hex_puzzles,
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

chia = Analysis([path_for_file("src.cmds.chia")],
             pathex=[path_for_file("aiter"), f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

farmer = Analysis([path_for_file("src.server.start_farmer")],
             pathex=[path_for_file("aiter"), f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

harvester = Analysis([path_for_file("src.server.start_harvester")],
             pathex=[path_for_file("aiter"), f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

daemon_pyz = PYZ(daemon.pure, daemon.zipped_data,
             cipher=block_cipher)
full_node_pyz = PYZ(full_node.pure, full_node.zipped_data,
             cipher=block_cipher)
wallet_pyz = PYZ(wallet.pure, wallet.zipped_data,
             cipher=block_cipher)
chia_pyz = PYZ(chia.pure, chia.zipped_data,
             cipher=block_cipher)
farmer_pyz = PYZ(farmer.pure, farmer.zipped_data,
             cipher=block_cipher)
harvester_pyz = PYZ(harvester.pure, harvester.zipped_data,
             cipher=block_cipher)

daemon_exe = EXE(daemon_pyz,
          daemon.scripts,
          [],
          exclude_binaries=True,
          name='daemon',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True )

full_node_exe = EXE(full_node_pyz,
          full_node.scripts,
          [],
          exclude_binaries=True,
          name='start_full_node',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False)

wallet_exe = EXE(wallet_pyz,
          wallet.scripts,
          [],
          exclude_binaries=True,
          name='start_wallet',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False)

chia_exe = EXE(chia_pyz,
          chia.scripts,
          [],
          exclude_binaries=True,
          name='chia',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False)

farmer_exe = EXE(farmer_pyz,
          farmer.scripts,
          [],
          exclude_binaries=True,
          name='start_farmer',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False)

harvester_exe = EXE(harvester_pyz,
          harvester.scripts,
          [],
          exclude_binaries=True,
          name='start_harvester',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False)

coll = COLLECT(daemon_exe,
               daemon.binaries,
               daemon.zipfiles,
               daemon.datas,

               full_node_exe,
               full_node.binaries,
               full_node.zipfiles,
               full_node.datas,

               wallet_exe,
               wallet.binaries,
               wallet.zipfiles,
               wallet.datas,

               chia_exe,
               chia.binaries,
               chia.zipfiles,
               chia.datas,

               farmer_exe,
               farmer.binaries,
               farmer.zipfiles,
               farmer.datas,

               harvester_exe,
               harvester.binaries,
               harvester.zipfiles,
               harvester.datas,

               strip = False,
               upx_exclude = [],
               name = 'daemon'
)
