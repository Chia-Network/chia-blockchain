# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from os import listdir
from os.path import isfile, join
from pkg_resources import get_distribution
from PyInstaller.utils.hooks import copy_metadata

# Include all files that end with clvm.hex
puzzles_path = "../src/wallet/puzzles"
puzzle_dist_path = "./src/wallet/puzzles"
onlyfiles = [f for f in listdir(puzzles_path) if isfile(join(puzzles_path, f))]

hex_puzzles = []
for file in onlyfiles:
    if file.endswith("clvm.hex"):
        hex_puzzles.append((f"{puzzles_path}/{file}", puzzle_dist_path))

keyring_imports = collect_submodules('keyring.backends')

# keyring uses entrypoints to read keyring.backends from metadata file entry_points.txt.
keyring_datas = copy_metadata('keyring')[0]
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
subcommand_modules = [f"../src.cmds.%s" % _ for _ in SUBCOMMANDS]
subcommand_modules.extend([f"src.cmds.%s" % _ for _ in SUBCOMMANDS])
other = ["aiter.active_aiter", "aiter.aiter_forker", "aiter.aiter_to_iter", "aiter.azip", "aiter.flatten_aiter", "aiter.gated_aiter",
"aiter.iter_to_aiter", "aiter.join_aiters", "aiter.map_aiter", "aiter.map_filter_aiter", "aiter.preload_aiter",
"aiter.push_aiter", "aiter.sharable_aiter", "aiter.stoppable_aiter", "win32timezone", "win32cred", "pywintypes", "win32ctypes.pywin32", "pkg_resources.py2_warn"]

entry_points = ["aiohttp", "aiohttp",
            "src.cmds.chia",
            "src.server.start_wallet",
            "src.server.start_full_node",
            "src.server.start_harvester",
            "src.server.start_farmer",
            "src.server.start_introducer",
            "src.server.start_timelord",
            "src.timelord_launcher",
            "src.util.bip39",
            "src.simulator.start_simulator"]

subcommand_modules.extend(other)
subcommand_modules.extend(entry_points)
subcommand_modules.extend(keyring_imports)

daemon = Analysis([f"../src/daemon/server.py"],
             pathex=[f"../venv/lib/python3.7/site-packages/aiter/", f"../"],
             binaries = [("../venv\Lib\site-packages\\*dll", '.',), ("C:\Windows\System32\\msvcp140.dll", '.',) , ("C:\Windows\System32\\vcruntime140_1.dll", '.',)],
             datas=[keyring_datas, version_data, (f"../src/util/initial-config.yaml", f"./src/util/") ] +
             hex_puzzles,
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

full_node = Analysis([f"../src/server/start_full_node.py"],
             pathex=[f"../venv/lib/python3.7/site-packages/aiter/", f"../"],
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

wallet = Analysis([f"../src/server/start_wallet.py"],
             pathex=[f"../venv/lib/python3.7/site-packages/aiter/", f"../"],
             binaries = [],
             datas=[(f"../mozilla-ca/cacert.pem", f"./mozilla-ca/"), (f"../src/ssl/dst_root_ca.pem", f"./src/ssl/"), (f"../src/ssl/chia_ca.key", f"./src/ssl/"), (f"../src/ssl/chia_ca.crt", f"./src/ssl/"), (f"../src/util/english.txt", f"./src/util/"), version_data ] + hex_puzzles,
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

chia = Analysis([f"../src/cmds/chia.py"],
             pathex=[f"../venv/lib/python3.7/site-packages/aiter/", f"../"],
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

farmer = Analysis([f"../src/server/start_farmer.py"],
             pathex=[f"../venv/lib/python3.7/site-packages/aiter/", f"../"],
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

harvester = Analysis([f"../src/server/start_harvester.py"],
             pathex=[f"../venv/lib/python3.7/site-packages/aiter/", f"../"],
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
