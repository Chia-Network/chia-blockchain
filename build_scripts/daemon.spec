# -*- mode: python ; coding: utf-8 -*-
#from chia.cmds.chia import SUBCOMMANDS
import pathlib

from pkg_resources import get_distribution

from os import listdir
from os.path import isfile, join
from PyInstaller.utils.hooks import copy_metadata

# Include all files that end with clvm.hex
puzzles_path = "../chia/wallet/puzzles"
puzzle_dist_path = "./chia/wallet/puzzles"
onlyfiles = [f for f in listdir(puzzles_path) if isfile(join(puzzles_path, f))]

hex_puzzles = []
for file in onlyfiles:
    if file.endswith("clvm.hex"):
        puzzle_path = f"{puzzles_path}/{file}"
        hex_puzzles.append((puzzles_path, puzzle_dist_path))

build = pathlib.Path().absolute()
root = build.parent

version_data = copy_metadata(get_distribution("chia-blockchain"))[0]

SUBCOMMANDS = [
    "configure",
    "farm",
    "init",
    "keys",
    "netspace",
    "plots",
    "run_daemon",
    "show",
    "start",
    "stop",
    "version",
    "wallet",
]
block_cipher = None
subcommand_modules = [f"{root}/chia.cmds.%s" % _ for _ in SUBCOMMANDS]
subcommand_modules.extend([f"chia.cmds.%s" % _ for _ in SUBCOMMANDS])
other = ["aiter.active_aiter", "aiter.aiter_forker", "aiter.aiter_to_iter", "aiter.azip", "aiter.flatten_aiter", "aiter.gated_aiter",
"aiter.iter_to_aiter", "aiter.join_aiters", "aiter.map_aiter", "aiter.map_filter_aiter", "aiter.preload_aiter",
"aiter.push_aiter", "aiter.sharable_aiter", "aiter.stoppable_aiter", "pkg_resources.py2_warn"]

entry_points = ["chia.cmds.chia",
            "chia.server.start_wallet",
            "chia.server.start_full_node",
            "chia.server.start_harvester",
            "chia.server.start_farmer",
            "chia.server.start_introducer",
            "chia.server.start_timelord",
            "chia.timelord_launcher",
            "chia.simulator.start_simulator"]

subcommand_modules.extend(other)
subcommand_modules.extend(entry_points)



daemon = Analysis([f"{root}/chia/daemon/server.py"],
             pathex=[f"{root}/venv/lib/python3.8/site-packages/aiter/", f"{root}"],
             binaries = [],
             datas=[version_data, (f"../chia/util/initial-config.yaml", f"./chia/util/"), ] +
             hex_puzzles,
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

full_node = Analysis([f"{root}/chia/server/start_full_node.py"],
             pathex=[f"{root}/venv/lib/python3.8/site-packages/aiter/", f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

wallet = Analysis([f"{root}/chia/server/start_wallet.py"],
             pathex=[f"{root}/venv/lib/python3.8/site-packages/aiter/", f"{root}"],
             binaries = [],
             datas=[(f"../mozilla-ca/cacert.pem", f"./mozilla-ca/"), (f"../chia/ssl/dst_root_ca.pem", f"./chia/ssl/"), (f"../chia/ssl/chia_ca.key", f"./chia/ssl/"), (f"../chia/ssl/chia_ca.crt", f"./chia/ssl/"), (f"../chia/util/english.txt", f"./chia/util/"), version_data ] + hex_puzzles,
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

chia = Analysis([f"{root}/chia/cmds/chia.py"],
             pathex=[f"{root}/venv/lib/python3.8/site-packages/aiter/", f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

farmer = Analysis([f"{root}/chia/server/start_farmer.py"],
             pathex=[f"{root}/venv/lib/python3.8/site-packages/aiter/", f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

harvester = Analysis([f"{root}/chia/server/start_harvester.py"],
             pathex=[f"{root}/venv/lib/python3.8/site-packages/aiter/", f"{root}"],
             binaries = [],
             datas=[version_data],
             hiddenimports=subcommand_modules,
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
