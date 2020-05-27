# -*- mode: python ; coding: utf-8 -*-
#from src.cmds.chia import SUBCOMMANDS
import pathlib

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

keyring_imports = collect_submodules('keyring.backends')

# keyring uses entrypoints to read keyring.backends from metadata file entry_points.txt.
keyring_datas = copy_metadata('keyring')[0]

from pkg_resources import get_distribution

build = pathlib.Path().absolute()
root = build.parent

from PyInstaller.utils.hooks import copy_metadata
version_data = copy_metadata(get_distribution("chia-blockchain"))[0]

SUBCOMMANDS = [
    "init",
    "keys",
    "show",
    "start",
    "stop",
    "version",
    "netspace",
    "run_daemon",
]
block_cipher = None
subcommand_modules = [f"{root}/src.cmds.%s" % _ for _ in SUBCOMMANDS]
other = ["aiter.active_aiter", "aiter.aiter_forker", "aiter.aiter_to_iter", "aiter.azip", "aiter.flatten_aiter", "aiter.gated_aiter",
"aiter.iter_to_aiter", "aiter.join_aiters", "aiter.map_aiter", "aiter.map_filter_aiter", "aiter.preload_aiter",
"aiter.push_aiter", "aiter.sharable_aiter", "aiter.stoppable_aiter","src.wallet.websocket_server", "win32timezone", "win32cred", "pywintypes", "win32ctypes.pywin32"]

entry_points = ["aiohttp", "aiohttp",
            "src.cmds.check_plots",
            "src.cmds.create_plots",
            "src.wallet.websocket_server",
            "src.server.start_full_node",
            "src.server.start_harvester",
            "src.server.start_farmer",
            "src.server.start_introducer",
            "src.server.start_timelord",
            "src.timelord_launcher",
            "src.simulator.start_simulator"]

subcommand_modules.extend(other)
subcommand_modules.extend(entry_points)
subcommand_modules.extend(keyring_imports)

daemon = Analysis([f"{root}/src/daemon/server.py"],
             pathex=[f"{root}/venv/lib/python3.7/site-packages/aiter/", f"{root}"],
             binaries = [(f"{root}/venv\Lib\site-packages\\*dll", '.')],
             datas=[keyring_datas, version_data, (f"../src/util/initial-config.yaml", f"./src/util/"),
             (f"../src/util/initial-plots.yaml", f"./src/util/") ],
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

full_node = Analysis([f"{root}/src/server/start_full_node.py"],
             pathex=[f"{root}/venv/lib/python3.7/site-packages/aiter/", f"{root}"],
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

wallet = Analysis([f"{root}/src/wallet/websocket_server.py"],
             pathex=[f"{root}/venv/lib/python3.7/site-packages/aiter/", f"{root}"],
             binaries = [],
             datas=[(f"../src/util/english.txt"), version_data ],
             hiddenimports=subcommand_modules,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

plotter = Analysis([f"{root}/src/cmds/create_plots.py"],
             pathex=[f"{root}/venv/lib/python3.7/site-packages/aiter/", f"{root}"],
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

farmer = Analysis([f"{root}/src/server/start_farmer.py"],
             pathex=[f"{root}/venv/lib/python3.7/site-packages/aiter/", f"{root}"],
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

harvester = Analysis([f"{root}/src/server/start_harvester.py"],
             pathex=[f"{root}/venv/lib/python3.7/site-packages/aiter/", f"{root}"],
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

check_plots = Analysis([f"{root}/src/cmds/check_plots.py"],
             pathex=[f"{root}/venv/lib/python3.7/site-packages/aiter/", f"{root}"],
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
plotter_pyz = PYZ(plotter.pure, plotter.zipped_data,
             cipher=block_cipher)
farmer_pyz = PYZ(farmer.pure, farmer.zipped_data,
             cipher=block_cipher)
harvester_pyz = PYZ(harvester.pure, harvester.zipped_data,
             cipher=block_cipher)
check_plots_pyz = PYZ(check_plots.pure, check_plots.zipped_data,
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
          name='websocket_server',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False)

plotter_exe = EXE(plotter_pyz,
          plotter.scripts,
          [],
          exclude_binaries=True,
          name='create_plots',
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
          farmer.scripts,
          [],
          exclude_binaries=True,
          name='start_harvester',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False)

check_plots_exe = EXE(check_plots_pyz,
          check_plots.scripts,
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

               plotter_exe,
               plotter.binaries,
               plotter.zipfiles,
               plotter.datas,

               farmer_exe,
               farmer.binaries,
               farmer.zipfiles,
               farmer.datas,

               harvester_exe,
               harvester.binaries,
               harvester.zipfiles,
               harvester.datas,

               check_plots_exe,
               check_plots.binaries,
               check_plots.zipfiles,
               check_plots.datas,
               strip = False,
               upx_exclude = [],
               name = 'daemon'
)
