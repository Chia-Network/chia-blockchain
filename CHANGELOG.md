# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project does not yet adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for setuptools_scm related reasons.

## [Unreleased]

### Added

- Windows and MacOS now have one click installers that then send users to a GUI on both platforms to farm or use their wallets. Windows is built on GitHub Actions and MacOS is also built on Azure Pipelines so as to build on Mojave.
- You can see and control your farmer, harvester, and plotter from the GUI on Windows, MacOS, and Linux.
- Create plots and see the plotting log from a GUI on Windows, MacOS, and Linux.
- You can now create or import private keys with a 24 word mnemonic, both in the UI and 'chia keys' command line.
- You can delete and change active keys from the GUI and cli.
- We added a new keychain system that replaces keys.yaml, and migrates existing users from keys.yaml. It utilizes each OS's keychain for slightly more secure key storage.
- We added a `chia keys` command line program, to see, add, and remove private keys.
- We added RPC servers and RPC client implementations for Farmer and Harvester. The new UI uses these for additional information and functionality.
- We added total network storage space estimation to the node RPC at the `/get_network_space` endpoint instead of only being available in the cli. The RPC endpoint takes two block header hashes and estimates space between those header hashes.
- Logs now autorotate. Once the debug.log reaches 20MB it is compressed and archived keeping 7 historical 20MB logs.
- We now have a CHANGELOG.md that adheres closely to the [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) standard. We merged in the version history and updated some previous release notes to capture items important to the change log. We are modifying our release process to accumulate changes at the top of the change log and then copy those to the release notes at the time of the release.
- We added [lgtm](https://lgtm.com/) source analysis on pull request to the chia-blockchain, chiapos, chiavdf, chiabip158, and bls-library repositories to add some automated security analysis to our ci.

### Changed

- Due to an issue with aggsig and aggsig-me, the beta 1.6 blockchain is not compatible with earlier chains.
- We replaced the Electron/JavaScript interface with a React user interface which is cleaner and more responsive.
- We now have a multithreaded harvester to farm more plots concurrently. This is especially faster when there are multiple disks being harvested. The class is also made thread safe with mutex guards. This is achieved by releasing GIL in the python bindings when fetching qualities and proofs. We estimate that the former guidance of only 50 plots per physical drive should be updated to 250-350 plots per physical drive. We will continue to improve the plots per physical drive limit during the beta period.
- Syncing a node is now much faster and uses less memory.
- `chia netspace` has been refactored to use the `/get_network_space` RPC. The command
  syntax has changed slightly. By default it calculates the last 24 blocks from the
  current LCA. Optionally you can use the `-b` flag to start the calculation from a different block
  height. Use `-d` to specify the delta number of blocks back into history to estimate over from either LCA or your `-b` block height.
- The Full node RPC response formats have been changed. All API calls now return a dict with success, and an additional value, for example {"success": True, "block": block}.
- chiapos is now easier to compile with MSVC.
- create plots now takes in an optional sk_seed, it is no longer read in from keys.yaml. If not passed in, it is randomly generated. The -i argument can now only be used when you provide an sk_seed.
- Moved to PyYAML 5.3.1 which prevents arbitrary code execution during python/object/new constructor.
- Moved to Python cryptography 2.9.2 which deprecates OpenSSL 1.0.1 and now relies upon OpenSSL 1.1.1g.
- Moved to aiosqlite 0.13.0 which adds official support for Python 3.8 and fixes a possible hung thread if a connection failed.

### Fixed

- In beta 1.5 we introduced a bug in aggsig and aggsig-me that we have fixed in this release. That forced a hard fork of the chain so coins and balances are lost from beta 1.5. There is no impact on existing plots.
- Starting and stopping servers now works much more reliably.
- `chia-check-plots` uses the plot root and checks the plots in the same manner as harvester.
- Fixed and issue where [Relic](https://github.com/relic-toolkit/relic) and thus blspy would crash on processors older than Haswell as they don't support lzc.
- Some non-critical networking errors are no longer logged.
- Blocks with compact proofs of time are now able to be updated into the node database.
- The `install-timelord.sh` script now correctly determines which version of python it is running under and correctly builds vdf_client and correctly links to vdf_bench. It also handles upgrading CMake on Ubuntu's older than 20.04LTS do satisfy the new CMake 3.14+ requirement to build Timelord.
- An issue in asyncio was not being caught correctly and that could cause nodes to crash.
- The build status shield layout is fixed in README.md
- Raspberry Pi 3/4 with Ubuntu 20.04LTS 64 bit should compile again.

## [1.0beta5] aka Beta 1.5 - 2020-05-05

### Added

- This release is primarily a maintenance release for Beta 1.4.
- We have added an option to `chia-create-plots` to specify the second temporary directory. Creating a plot is a three step process. First a working file ending in `.dat.tmp` is created. This file is usually 5 times larger than the final plot file. In the later stages of plotting a second temp file is created ending in `.dat.2.tmp` which will grow to the size of the final plot file. In the final step, the `.dat.2.tmp` is copied to the final `.dat` plot file. You can now optionally set the directory for the `.dat.2.tmp` file with the `-2` flag. An example use case is plotting on a ramdisk and writing both the second temp file and the final file out to an SSD - `chia-create-plots -n 1 -k 30 -t /mnt/ramdisk -2 /mnt/SSD -d /mnt/SSD`.

### Changed

- `chia init` properly migrates from previous versions including the k>=32 workaround. Additionally, the farming target key is checked to make sure that it is the valid and correct public key format.
- We have implemented a workaround for the `chia start` issues some were having upon crash or reboot. We will be rebuilding start and stop to be robust across platforms.
- This release re-includes `chia-start-harvester`.
- Coloured coins now have a prefix to help identify them. When sending transactions, the new prefix is incompatible with older clients.
- The user interface now refers to chia coins with their correct currency code of XCH.
- The next release will now be in the dev branch instead of the e.g. beta-1.5. Additionally we are enforcing linear merge into dev and prefer rebase merges or partial squash merges of particularly chatty commit histories.
- Building the sub reposities (chiapos, chiavdf, blslibrary) now requires CMake 3.14+.

### Fixed

- There was a regression in Chia Proof of Space ([chiapos](https://github.com/Chia-Network/chiapos)) that came from our efforts to speed up plotting on Windows native. Now k>=32 plots work correctly. We made additional bug fixes and corrected limiting small k size generation.
- There was a bug in Timelord handling that could stop all VDF progress.

### Deprecated

- We have made significant changes to the full node database to make it more reliable and quicker to restart. This requires re-syncing the current chain. If you use `chia init` then sync on first start will happen automatically. "\$CHIA_ROOT" users will need to delete `$CHIA_ROOT/db/*` before starting Beta 1.5. This also fixes the simulation issue in Beta 1.4 where tips could go "back in time."

### Known issues

- uPnP support on Windows may be broken. However, Windows nodes will be able to connect to other nodes and, once connected, participate fully in the network.
- Currently, there is no way to restore a Coloured Coin Wallet.

## [1.0beta4] aka Beta 1.4 - 2020-04-29

### Added

- This release adds Coloured coin support with offers. Yes that is the correct spelling. Coloured coins allow you to issue a coin, token, or asset with nearly unlimited issuance plans and functionality. They support inner smart transactions so they can inherit any of the other functionality you can implement in Chialisp. Offers are especially cool as they create a truly decentralized exchange capability. Read much more about them in Bram's [blog post on Coloured coins](https://chia.net/2020/04/29/coloured-coins-launch.en.html).
- This release adds support for native Windows via a (mostly) automated installer and MacOS Mojave. Windows still requires some PowerShell command line use. You should expect ongoing improvements in ease of install and replication of the command line tools in the GUI. Again huge thanks to @dkackman for continued Windows installer development. Native Windows is currently slightly slower than the same version running in WSL 2 on the same machine for both block verification and plotting.
- We made some speed improvements that positively affected all platforms while trying to increase plotting speed in Windows.
- The graphical Full Node display now shows the expected finish times of each of the prospective chain tips.
- Now you can run estimates of the total space currently farming the network. Try `chia netspace -d 12` to run an estimate over the last 12 blocks which is approximately 1 hour.
- We’ve added TLS authentication for incoming farmer connections. TLS certs and keys are generated during chia init and only full nodes with your keys will be able to connect to your Farmer. Also, Harvester, Timelord, and Wallet will now not accept incoming connections which reduces the application attack surface.
- The node RPC has a new endpoint get_header_by_height which allows you to retrieve the block header from a block height. Try `chia show -bh 1000` to see the block header hash of block 1000. You can then look up the block details with `chia show -b f655e1a9f7f8c89a703e40d9ce82ae33508badaf7b37fa1a56cad27926b5e936` which will look up a block by it's header hash.
- Our Windows binaries check the processor they are about to run on at runtime and choose the best processor optimizations for our [MPIR](http://mpir.org/) VDF dependency on Windows.
- Most of the content of README.md and INSTALL.md have been moved to the [repository wiki](https://github.com/Chia-Network/chia-blockchain/wiki) and placed in [INSTALL](https://github.com/Chia-Network/chia-blockchain/wiki/INSTALL) and [Quick Start Guide](https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide)
- Harvester is now asynchronous and will better be able to look up more plots spread across more physical drives.
- Full node startup time has been sped up significantly by optimizing the loading of the blockchain from disk.

# Changed

- Most scripts have been removed in favor of chia action commands. You can run `chia version` or `chia start node` for example. Just running `chia` will show you more options. However `chia-create-plots` continues to use the hyphenated form. Also it's now `chia generate keys` as another example.
- Chia start commands like `chia start farmer` and `chia stop node` now keep track of process IDs in a run/ directory in your configuration directory. `chia stop` is unlikely to work on Windows native for now. If `chia start -r node` doesn't work you can force the run/ directory to be reset with `chia start -f node`.
- We suggest you take a look at our [Upgrading documentation](https://github.com/Chia-Network/chia-blockchain/wiki/Updating-beta-software) if you aren't performing a new install.
- blspy now has libsodium included in the MacOS and Linux binary wheels.
- miniupnpc and setprotitle were dynamically checked for an installed at runtime. Removed those checks and we rely upon the install tools installing them before first run.
- Windows wheels that the Windows Installer packages are also available in the ci Artifacts in a .zip file.
- The script `chia start wallet-gui` has been chaned to `chia start wallet` which launches but the GUI and server on MacOS and Linux. `chia start wallet-server` remains for WSL 2 and Windows native.

### Deprecated

- This release breaks the wire protocol so it comes with a new chain. As we merged in Coloured coins we found that we needed to change how certain hashes were managed. Your 1.0beta3 coin balances will be lost when you upgrade but your plots will continue to work on the 1.0beta4 chain. Since we had to make a breaking wire protocol change we accelerated changing our hash to prime function for starting proofs of time. That was also going to be a future breaking change.

### Known issues

- Plots of k>=32 are not working for farming, and some broken plots can cause a memory leak. A [workaround is available](https://github.com/Chia-Network/chia-blockchain/wiki/Beta-1.4-k=32-or-larger-work-around).
- If you are running a simulation, blockchain tips are not saved in the database and this is a regression. If you stop a node it can go back in time and cause an odd state. This doesn't practically effect testnet participation as, on restart, node will just sync up a few blocks to the then current tips.
- uPnP support on Windows may be broken. However, Windows nodes will be able to connect to other nodes and, once connected, participate fully in the network.
- Coins are not currently reserved as part of trade offers and thus could potentially be spent before the offer is accepted resulting in a failed offer transaction.
- Currently, there is no way to restore a Coloured Coin Wallet.
- The `chia stop all` command sometimes fails, use `chia-stop-all` instead. In windows, use the task manager to stop the servers.

## [1.0beta3] aka Beta 1.3 - 2020-04-08

### Added

- Windows, WSL 2, Linux and MacOS installation is significantly streamlined. There is a new Windows installer for the Wallet GUI (huge thanks to @dkackman).
- All installs can now be from the source repository or just the binary dependencies on WSL 2, most modern Linuxes, and MacOS Catalina. Binary support is for both Python 3.7 and 3.8.
- There is a new migration tool to move from Beta1 (or 2) to Beta3. It should move everything except your plots.
- There is a new command `chia init` that will migrate files and generate your initial configuration. If you want to use the Wallet or farm, you will also have to `chia-generate-keys`. You can read step by step instructions for [upgrading from a previous beta release](https://github.com/Chia-Network/chia-blockchain/wiki/Updating-beta-software). If you've set `$CHIA_ROOT` you will have to make sure your existing configuration remains compatible manually.
- Wallet has improved paper wallet recovery support.
- We now also support restoring old wallets with only the wallet_sk and wallet_target. Beta3's Wallet will re-sync from scratch.
- We've made lots of little improvements that should speed up node syncing
- We added full block lookup to `chia show`.

# Changed

- `chia-restart-harvester` has been renamed from `chia-start-harvester` to better reflect its functionality. Use it to restart a harvester that's farming so that it will pick up newly finished plots.
- We made the Wallet configurable to connect to a remote trusted node.
- We now have farmers reconnect to their trusted node if they lose contact.
- We updated our miniupnpc dependency to version 2.1.
- We increase the default farmer propagate threshold to reduce chain stall probability.

# Deprecated

- You should not copy over any prior Wallet database as they are not compatible with Beta3. Your existing full node will not have to re-sync and its database remains compatible.

#Fixed

- Among a lot of bug fixes was removing a regression that slowed plotting on MacOS by 3 times and may have had smaller impacts on plotting speed on other platforms.
- We've removed some race conditions in the Wallet
- We resolved the "invalid blocks could disconnect farmers" bug
- We and upped the default tls certificate size to 2048 for some unhappy operating systems.

### Known issues

- Windows native is close but not here yet. Also, we should be adding back MacOS Mojave support shortly.
- So why is this Beta 3 you're wondering? Well, we're getting used to our new release management tools and a hotfix devoured our beta2 nomenclature... We've marked it YANKED here.
- If you previously used the plot_root variable in config, your plot directory names might not migrate correctly. Please double check the filenames in `~/.chia/beta-1.0b3/config/plots.yaml` after migrating

## [1.0beta2] aka Beta 1.2 - 2020-04-04 [YANKED]

## [1.0beta1] aka Beta 1.0 - 2020-04-02

### Added

- There is now full transaction support on the Chia blockchain. In this initial Beta 1.0 release, all transaction types are supported though the wallets and UIs currently only directly support basic transactions like coinbase rewards and sending coins while paying fees. UI support for our [smart transactions](https://github.com/Chia-Network/wallets/blob/master/README.md) will be available in the UIs shortly.
- Wallet and Node GUI’s are available on Windows, Mac, and desktop Linux platforms. We now use an Electron UI that is a full light client wallet that can also serve as a node UI. Our Windows Electron Wallet can run standalone by connecting to other nodes on the network or another node you run. WSL 2 on Windows can run everything except the Wallet but you can run the Wallet on the native Windows side of the same machine. Also the WSL 2 install process is 3 times faster and _much_ easier. Windows native node/farmer/plotting functionality are coming soon.
- Install is significantly easier with less dependencies on all supported platforms.
- If you’re a farmer you can use the Wallet to keep track of your earnings. Either use the same keys.yaml on the same machine or copy the keys.yaml to another machine where you want to track of and spend your coins.
- We have continued to make improvements to the speed of VDF squaring, creating a VDF proof, and verifying a VDF proof.

# Changed

- We have revamped the chia management command line. To start a farmer all you have to do is start the venv with `. ./activate` and then type `chia-start-farmer &`. The [README.md](https://github.com/Chia-Network/chia-blockchain/blob/master/README.md) has been updated to reflect the new commands.
- We have moved all node to node communication to TLS 1.3 by default. For now, all TLS is unauthenticated but certain types of over the wire node to node communications will have the ability to authenticate both by certificate and by inter protocol signature. Encrypting over the wire by default stops casual snooping of transaction origination, light wallet to trusted node communication, and harvester-farmer-node communication for example. This leaves only the mempool and the chain itself open to casual observation by the public and the various entities around the world.
- Configuration directories have been moved to a default location of HomeDirectory/.chia/release/config, plots/ db/, wallet/ etc. This can be overridden by `export CHIA_ROOT=~/.chia` for example which would then put the plots directory in `HomeDirectory/.chia/plots`.
- The libraries chia-pos, chia-fast-vdf, and chia-bip-158 have been moved to their own repositories: [chiapos](https://github.com/Chia-Network/chiapos), [chiavdf](https://github.com/Chia-Network/chiavdf), and [chaibip158](https://github.com/Chia-Network/chiabip158). They are brought in by chia-blockchain at install time. Our BLS signature library remains at [bls-signatures](https://github.com/Chia-Network/bls-signatures).
- The install process now brings in chiapos, chiavdf, etc from Pypi where they are auto published via GitHub Actions ci using cibuildwheel. Check out `.github/workflows/build.yml` for build methods in each of the sub repositories.
- `chia-regenerate-keys` has been renamed `chia-generate-keys`.
- setproctitle is now an optional install dependency that we will continue to install in the default install methods.
- The project now defaults to `venv` without the proceeding . to better match best practices.
- Developer requirements were separated from the actual requirements.
- `install-timelord.sh` has been pulled out from `install.sh`. This script downloads the source python package for chiavdf and compiles it locally for timelords. vdf_client can be included or excluded to make building normal user wheels easier.

# Removed

- The Beta release is not compatible with the history of the Alpha blockchain and we will be ceasing support of the Alpha chain approximately two weeks after the release of this Beta. However, your plots and keys are fully compatible with the Beta chain. Please save your plot keys! Examples of how to save your keys and upgrade to the Beta are available on the [repo wiki](https://github.com/Chia-Network/chia-blockchain/wiki).
- The ssh ui and web ui are removed in favor of the cli ui and the Electron GUI. To mimic the ssh ui try `chia show -s -c` and try `chia show --help` for usage instructions.
- We have removed the inkfish vdf implementation and replaced it with the pybind11 C++ version.

### Known Issues

- Wallet currently has limited support for restoring from a paper wallet. Wallet uses hierarchically deterministic keys, and assumes that any keys that are at index "higher than one" have not been used yet. If you have received a payment to an address associated with a key at a higher index and you want it to appear in Wallet, the current work around is to press the "NEW ADDRESS" button multiple times shortly after sync start. That will make wallet "aware of" addresses at higher indexes. Full support for paper wallet restoration will be added soon.
- We. Don't... Have.. Windows.... Native. YET!?! But the entire project is compiling on Windows 10 natively. Assistance would be more than appreciated if you have experience building binary python wheels for Windows. We are pushing some limits like uint-128, avx-2, avx-512, and AES-NI so it's not as easy as it looks...

## [Alpha 1.5.1] - 2020-03-24

### Fixed

- Fixed a bug in harvester that caused plots not to be farmed.

## [Alpha 1.5] - 2020-03-08

### Added

- You can now provide an index to create_plots using the -i flag to create an arbitrary new plot derived from an existing plot key. Thanks @xorinox.
- There is a new restart_harvester.sh in scripts/ to easily restart a harvester when you want to add a newly completed plot to the farm without restarting farmer, fullnode, timelord, etc.
- Harvesters now log errors if they encounter a malformed or corrupted plot file. Again thanks @xorinox.
- New AJAX based full node UI. To access go to http://127.0.0.1:8555/index.html with any modern web browser on the same machine as the full node.
- If you want to benchmark your CPU as a VDF you can use vdf_bench square_asm 500000 for the assembly optimized test or just vdf_bench square 500000 for the plain C++ code path. This tool is found in lib/chiavdf/fast_vdf/.
- Improvements to shutting down services in all of the scripts in scripts/. Another @xorinox HT.

### Changed

- VDF verification code is improved and is now more paranoid.
- Timelords can now be run as a cluster of VDF client instances around a central Timelord instance.. Instructions are available in the Cluster Timelord section of the repo wiki.

### Fixed

- Thanks @dkackman for clean ups to the proof of space code.
- Thanks to @davision for some typo fixes.

## [Alpha 1.4.1] - 2020-03-06

### Fixed

- Stack overflow in verifier

## [Alpha 1.4] - 2020-02-19

### Added

- Compiling and execution now detect AES-NI, or a lack of it, and fall back to a software AES implementation.
- Software AES adds support for Raspberry Pi 4, related ARM processors and Celeron processors.
- Added install instructions for CentOS/RHEL 8.1.
- Plotting working directory and final directory can both be specified in config.yaml
- Proof of space binary and create_plots scripts now allows passing in temp and final directories.
- Plotting now logs a timestamp at each major step.
- Added support for Python 3.8.

### Changed

- Due to changes to the sqlite database that are not backwards compatible, re-synch will be required.
- Loading the blockchain only loads headers into memory instead of header blocks (header + proofs), speeds up the startup, and reduces normal operation memory usage by 80%.
- Memory access is now synchronous to reduce use of locks and speed up block processing.
- Chia fullnode, farmer and harvester now default to logging to chia.log in the chia-blockchain directory. This is configured in config.yaml and due to config.yaml changes it is recommended to edit the new template config instead of using older config.yaml’s from previous versions.
- uvloop is now an optional add on.
- Harvester/farmer will not try to farm plots that they don’t have the key for.

### Fixed

- Thanks to @A-Caccese for fixes to Windows WSL instructions.
- Thanks @dkackman who also fixed some compiler warnings.

## [Alpha 1.3] - 2020-01-21

### Added

- FullNode performance improvements - Syncing up to the blockchain by importing all blocks is faster due to improvements in VDF verification speed and multithreading block verification.
- VDF improvements - VDF verification and generation speed has increased and dependence on flint2 has been removed. We wish to thank Dr. William Hart (@wbhart) for dual licensing parts of his contributions in FLINT and Antic for inclusion in the Chia blockchain.
- Implemented an RPC interface with JSON serialization for streamables - currently on port 8555.
- Added details on how to contribute in CONTRIBUTING.md. Thanks @RichardLitt.
- Added color logging
- Now chia_harvester will periodically announce which plots it is currently farming and their k sizes.

### Changed

- Moved the ssh UI to use RPC.
- Changed the displayed process names for harvester, farmer, fullnode, timelords, and VDFs to to chia_full node, chia_harvester, etc. Fixed a bug that could cause inadvertent shutdown of other processes like an ongoing plotting session when new chia services were started.
- Clarified the minimum version of boost required to build timelord/VDFs. Hat tip @AdrianScott
- Consensus and related documentation moved to the repository wiki.

### Fixed

- Fixed a bug where the node may not sync if it restarts close to a tip.
- Fixed a typo in the UI. Hat tip to @lvcivs for the pr.
- Fixed a memory leak in qfb_nudupl.
- Lots of smaller bug and documentation fixes.

### Removed

- Mongodb removed and replaced with SQLite for the blockchain database. This will require nodes to re-sync with the network. Luckily this is now faster.

## [Alpha 1.2] - 2020-01-08

### Added

- Performance improvements
  - Removes database access from blockchain, and handles headers instead of blocks
  - Avoid processing blocks and unfinished blocks that we have already seen.
  - Also adds test for load.

### Changed

- Improvements to plotting via lookup table - as much as 15% faster

### Fixed

- Fixed a blockchain initialization bug

## [Alpha 1.1.1] - 2019-12-25

### Added

- Added install instructions for Windows using WSL and Ubuntu.
- Added install instructions for CentOS 7.7.
- Added install instructions for Amazon Linux 2.
- New install_timelord.sh.

### Changed

- Installation is now separated into everything except timelord/vdf and timelord/vdf.
- replaced VDF server compilation scripts with Makefile

### Fixed

- setuptools_scm was corrupting .zip downloads of the repository.

## [Alpha 1.1] - 2019-12-12

### Added

- Introducer now makes sure it only sends peer addresses to peers of peers that it can reach on port 8444 or their UPnP port.
- We are now using setuptools_scm for versioning.

### Changed

- Timelord VDF submission and management logic upgraded.

### Fixed

- FullNode: A long running or low ulimit situation could cause an “out of files” issue which would stop new connection creation. Removed the underlying socket leak.
- FullNode: Multiple SSH UI bugs fixed.
- Harvester: Farming a plot of k = 30 or greater could lead to a segfault in the harvester.
- Updated blspy requirement to address an issue in the underlying bls-signatures library.

## [Alpha 1.0] - 2019-12-05

### Added

- This is the first release of the Chia testnet! Blockchain consensus, proof of time, and proof of space are included.
- More details on the release at https://www.chia.net/developer/

[unreleased]: https://github.com/Chia-Network/chia-blockchain/compare/1.0beta5...dev
[1.0beta5]: https://github.com/Chia-Network/chia-blockchain/compare/1.0beta4...1.0beta5
[1.0beta4]: https://github.com/Chia-Network/chia-blockchain/compare/1.0beta3...1.0beta4
[1.0beta3]: https://github.com/Chia-Network/chia-blockchain/compare/1.0beta2...1.0beta3
[1.0beta2]: https://github.com/Chia-Network/chia-blockchain/compare/1.0beta1...1.0beta2
[1.0beta1]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.5.1...1.0beta1
[alpha 1.5.1]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.5...alpha-1.5.1
[alpha 1.5]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.4.1...alpha-1.5
[alpha 1.4.1]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.4...alpha-1.4.1
[alpha 1.4]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.3...alpha-1.4
[alpha 1.3]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.2...alpha-1.3
[alpha 1.2]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.1.1...alpha-1.2
[alpha 1.1.1]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.1...alpha-1.1.1
[alpha 1.1]: https://github.com/Chia-Network/chia-blockchain/compare/alpha-1.0...alpha-1.1
[alpha 1.0]: https://github.com/Chia-Network/chia-blockchain/releases/tag/Alpha-1.0
