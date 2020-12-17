# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project does not yet adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for setuptools_scm/PEP 440 reasons.

## Unreleased

### Added

- The UI now warns if you attempt to create a plot smaller than k=32.
- You can now specify which private key to use for `chia plots create`. After obtaining the fingerprint from `chia keys show`, try `chia plots create -a FINGERPRINT`. Thanks to @eFishCent for this pull request!
- We now fully support Python 3.9.

### Changed

- There are new farming and plotting pages. The plotting flow was redesigned to streamline it and add advanced options as drop downs as appropriate. Plots are now queued into your local plot list. To see the plotting log, try the three vertical dots. Remote harvester plot display will be coming to the plot page as well.
- Harvester and farmer will start when the GUI starts instead of waiting for key selection.
- Plotting has a new option `-e`. This allows you to choose from either the default bitfield back propagation or the classic back propagation. SSD temp space is generally faster with the classic mode with `-e` and spinning disk are generally faster with the new method. YMMV.
- We have moved to taproot across all of our transactions and smart transactions.
- The rate limited wallet was updated and re-factored.
- All appropriate Chialisp smart transactions have been updated to use aggsig_me.
- Full node should be more aggressive about finding other peers.
- Peer disconnect messages are now set to log level INFO down from WARNING.
- chiavdf now allows passing in input to a VDF for new consensus.
- sha256tree has been removed from Chialisp.
- aiohttp, clvm-tools, colorlog, concurrent-log-handler, keyring, cryptography, and sortedcontainers have been upgraded to their current versions.
- Tests now place a cache of blocks in the ~/.chia/ directory to speed up total testing time.

### Fixed

- There was a regression in Beta 18 where the plotter took 499GiB of temp space for a k32 when it used to only use 332GiB. The plotter should now use just slightly less than it did in Beta 17.
- blspy was bumped to 0.3.0 which now correctly supports the aggsig of no signatures.

## [1.0beta18] aka Beta 1.18 - 2020-12-03

### Added

- F1 generation in the plotter is now fully parallel for a small speedup.
- We have bitfield optimized phase 2 of plotting. There is only about a 1% increase in speed from this change but there is a 12% decrease in writes with a penalty of 3% more reads. More details in [PR 120](https://github.com/Chia-Network/chiapos/pull/120). Note that some sorts in phase 2 and phase 3 will now appear "out of order" and that is now expected behavior.
- Partial support for Python 3.9. That includes new versions of Chia dependencies like chiabip158.

### Changed

- We have moved from using gulrak/filesystem across all platforms to only using it on MacOS. It's required on MacOS as we are still targeting Mojave compatibility. This should resolve Windows path issues.
- We upgraded to cbor 5.2.0 but expect to deprecate cbor in a future release.

### Fixed

- A segfault caused by memory leaks in bls-library has been fixed. This should end the random farmer and harvester crashes over time as outlined in [Issue 500](https://github.com/Chia-Network/chia-blockchain/issues/500).
- Plotting could hang up retrying in an "error 0" state due to a bug in table handling in some edge cases.
- CPU utilization as reported in the plotter is now accurate for Windows.
- FreeBSD and OpenBSD should be able to build and install chia-blockchain and its dependencies again.
- Starting with recent setuptools fixes, we can no longer pass an empty string to the linker on Windows when building binary wheels in the sub repos. Thanks @jaraco for tracking this down.

## [1.0beta17] aka Beta 1.17 - 2020-10-22

### Changed

- Bumped aiohttp to 3.6.3

### Fixed

- In the GUI there was [a regression](https://github.com/Chia-Network/chia-blockchain/issues/484) that removed the scroll bar on the Plot page. The scroll bar has returned!
- In Dark Mode you couldn't read the white on white plotting log text.
- To fix a bug in Beta 15's plotter we introduced a fixed that slowed plotting by as much as 25%.
- Certain NTFS root mount points couldn't be used for plotting or farming.
- Logging had [a regression](https://github.com/Chia-Network/chia-blockchain/issues/485) where log level could no longer be set by service.

## [1.0beta16] aka Beta 1.16 - 2020-10-20

### Added

- The Chia GUI now supports dark and light mode.
- The GUI now supports translations and localizations. If you'd like to add your language you can see the examples in [the locales directory](https://github.com/Chia-Network/chia-blockchain/tree/dev/electron-react/src/locales) of the chia-blockchain repository.
- `chia check plots` now takes a `-g` option that allows you to specify a matching path string to only check a single plot file, a wild card list of plot files, or all plots in a single directory instead of the default behavior of checking every directory listed in your config.yaml. A big thank you to @eFishCent for this pull request!
- Better documentation of the various timelord options in the default config.yaml.

### Changed

- The entire GUI has been refactored for code quality and performance.
- Updated to chiapos 0.12.32. This update significantly speeds up the F1/first table plot generation. It also now can log disk usage while plotting and generate graphs. More details in the [chiapos release notes](https://github.com/Chia-Network/chiapos/releases/tag/0.12.32).
- Node losing or not connecting to another peer node (which is entirely normal behaviour) is now logged at INFO and not WARNING. Your logs will be quieter.
- Both the GUI and CLI now default to putting the second temporary directory files into the specified temporary directory.
- SSL Certificate handling was refactored along with Consensus constants, service launching, and internal configuration management.
- Updated to clvm 0.5.3. This fixed a bug in the `point_add` operator, that was causing taproot issues. This also removed the `SExp.is_legit_list` function. There were significant refactoring of various smart transactions for simplicity and efficiency.
- WalletTool was generally removed.
- Deprecated pep517.build for the new standard `python -m build --sdist --outdir dist .`

### Fixed

- A bug in bls-singatures/blspy could cause a stack overflow if too many signatures were verified at once. This caused the block of death at 11997 of the Beta 15 chain. Updated to 0.2.4 to address the issue.
- GUI Wallet now correctly updates around reorgs.
- chiapos 0.12.32 fixed a an out of bounds read that could crash the plotter. It also contains a fix to better handle the case of drive letters on Windows.
- Node would fail to start on Windows Server 2016 with lots of cores. This [python issue explains]( https://bugs.python.org/issue26903) the problem.

### Known Issues

- On NTFS, plotting and farming can't use a path that includes a non root mountpoint. This is fixed in an upcoming version but did not have enough testing time for this release.

## [1.0beta15] aka Beta 1.15 - 2020-10-07

### Added

- Choosing a larger k size in the GUI also increases the default memory buffer.

### Changed

- The development tool WalletTool was refactored out.
- Update to clvm 0.5.3.
- As k=30 and k=31 are now ruled out for mainnet, the GUI defaults to a plot size of k=32.

### Fixed

- Over time the new peer gossip protocol could slowly disconnect all peers and take your node offline.
- Sometimes on restart the peer connections database could cause fullnode to crash.

## [1.0beta14] aka Beta 1.14 - 2020-10-01

### Added

- Node peers are now gossiped between nodes with logic to keep connected nodes on disparate internet networks to partially protect from eclipse attacks. This is the second to last step to remove our temporary introducer and migrate to DNS introducers with peer gossip modeled directly off of Bitcoin. This adds a new database of valid peer nodes that will persist across node restarts. This also makes changes to config.yaml's contents.
- For 'git clone' installs there is now a separate install-gui.sh which speeds up running install.sh for those who wish to run headless and makes docker and other automation simpler.
- The rate limited wallet library now supports coin aggregation for adding additional funds after the time of creation.
- Fees are now used in all applicable rate limited wallet calls
- New parameters for plotting: -r (number of threads) -s (stripe size) -u (number of buckets) in cli and GUI
- chiavdf now has full IFMA optimizations for processors that support it.

### Changed

- Multithreading support in chiapos, as well as a new algorithm which is faster and does 70% less IO. This is a significant improvement in speed, much lower total writing, and configurability for different hardware environments.
- Default -b changed to 3072 to improve performance
- The correct amount of memory is used for plotting
- `sh install.sh` was upgraded so that on Ubuntu it will install any needed OS dependencies.
- Wallet and puzzlehash generation have been refactored and simplified.
- Wallet has had various sync speed ups added.
- The rpc interfaces of all chia services have been refactored, simplified, and had various additional functionality added.
- Block timestamps are now stored in the wallet database. Both database versions were incremented and databases from previous versions will not work with Beta 14. However, upon re-sync all test chia since Beta 12 should appear in your wallet.
- All vestigial references to plots.yaml have been removed.

### Fixed

- Temporary space required for each k size was updated with more accurate estimates.
- Tables in the README.MD were not rendering correctly on Pypi. Thanks again @altendky.
- Chiapos issue where memory was spiking and increasing
- Fixed working space estimates so they are exact
- Log all errors in chiapos
- Fixed a bug that was causing Bluebox vdfs to fail.

## [1.0beta13] aka Beta 1.13 - 2020-09-15

### Added

### Changed

- Long_description_content_type is now set to improve chia-blockchian's Pypi entry. Thanks to @altendky for this pull request.
- A minor edit was made to clarify that excessive was only related to trolling in the Code of Conduct document.

### Fixed

- When starting the GUI from an installer or the command line on Linux, if you had not previously generated a key on your machine, the generate new key GUI would not launch and you would be stuck with a spinner.
- Farmer display now correctly displays balance.

## [1.0beta12] aka Beta 1.12 - 2020-09-14

### Added

- Rate limited wallets can now have unspent and un-spendable funds clawed back by the Admin wallet.
- You can now backup your wallet related metadata in an encrypted and signed file to a free service from Chia Network at backup.chia.net. Simply having a backup of your private key will allow you to fully restore the state of your wallet including coloured coins, rate limited wallets, distributed identity wallets and many more. Your private key is used to automatically restore the last backup you saved to the Chia backup cloud service. This service is open source and ultimately you will be able to configure your backups to go to backup.chia.net, your own installation, or a third party's version of it.
- Added a Code of Conduct in CODE_OF_CONDUCT.md.
- Added a bug report template in `.github/ISSUE_TEMPLATE/bug_report.md`.

### Changed

- This is a new blockchain as we changed how the default puzzle hashes are generated and previous coins would not be easy to spend. Plots made with Beta 8 and newer continue to work, but all previous test chia are left on the old chain and do not migrate over. Configuration data like plot directories automatically migrate in your `~/.chia` directory.
- Proof of Space now requires significantly less temp space to generate a new plot. A k=32 that used to require 524GiB now requires only 313GiB - generally a 40% decrease across all k sizes.
- When plotting, instead of 1 monolithic temp file, there are now 8 files - one for each of the 7 tables and one for sorting plot data. These files are deleted as the `-2` or `-d` final file is written so the final file can fit within the footprint of the temporary files on the same filesystem.
- We've made various additional CPU optimizations to the Proof of Space plotter that reduces plotting time by an additional 13%. These changes will also reduce CPU utilization in harvesting.
- We have ruled out k=30 for mainnet minimum plot size. k=31 may still make mainnet. k=32 and larger will be viable on mainnet.
- We moved to react-styleguidist to develop reusable components in isolation and better document the UI. Thanks to @embiem for this pull request.
- Coloured coins have been updated to simplify them, remove 'a', and stop using an 'auditor'.
- clvm has been significantly changed to support the new coloured coins implementation.
- Bumped cryptography to 3.1. Cryptography is now publishing ARM64 binary wheels to PyPi so Raspberry Pi installs should be even easier.
- `chia init` now automatically discovers previous releases in each new release.

### Fixed

- `chia show -w` should now more reliably work. Wallet balances should be more often correct.
- View -> Developer -> Developer Tools now correctly opens the developer tools. Thank you to @roxaaams for this pull request!
- Fixed 'Receive Address' typo in Wallet. Thanks @meurtn on Keybase.
- Fixed a typo in `chia show -w` with thanks to @pyl on Keybase.
- In Windows the start menu item is now Chia Network and the icon in Add/Remove is updated.

## [1.0beta11] aka Beta 1.11 - 2020-08-24

### Added

- The Chia UI now has a proper About menu entry that gives the various component versions and directs people to submit issues on GitHub. Thank you to @freddiecoleman for this pull request!
- Ability to run only the farmer, wallet, or timelord services, for more advanced configurations (chia run farmer-only, wallet-only, timelord-only)

### Changed

- To complement the new About menu, we have revamped all Electron menus and made them OS native. There are now direct links to the Wiki, Keybase, and FAQ in the Help menu.
- There are minor improvements to how working space is calculated and displayed by the plotter. The plotter also has additional debugging information in its output.
- Successful plots only have an atomic rename.

### Fixed

- kOffsetSize should have been 10 bits and not 9. This was causing plots, especially larger plots, to fail with "Error 0". This bug was introduced in Beta 8 with the new plot file format.
- A bug in aiosqlite was causing tests to hang - especially on the ci. This may also have been causing wallet database corruption.
- `chia show -w` now correctly outputs all wallet types and balances from the local wallet.

## [1.0beta10] aka Beta 1.10 - 2020-08-18

### Added

- Meet our new Rate Limited wallet. You can now fund a wallet from an Admin wallet that will set how many coins can be spent over a given range of blocks for a given User wallet. Once combined with on chain wallet recovery, this makes it much easier to secure your "spending money" wallet so that if it is compromised you have time to get most of the funds back before an attacker can steal them all. This wallet should be considered alpha in this release as additional fixes and functionality will be coming in subsequent releases.
- We've added unhardened HD keys to bls-signatures for the smart wallets that need them. We've added significant cross project testing to our BLS implementation.
- The python implementation of bls-signatures is now current to the new specification.
- `chia show -b` now returns plot public key and pool public key for each block.
- Added cbor2 binary wheels for ARM64 to the Chia simple site. Raspberry Pi should be just a little easier to install.

### Changed

- Wallet addresses and other key related elements are now expressed in Chech32 which is the Chia implementation of [Bech32](https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki). All of your old wallet addresses will be replaced with the new Chech32 addresses. The only thing you can't do is send test chia between 1.8/1.9 and 1.10 software. Anyone who upgrades to 1.10 will keep their transactions and balances of test chia from the earlier two releases however.
- We added a first few enhancements to plotting speed. For a k=30 on a ramdisk with `-b 64 GiB` it results in an 11% speedup in overall plotting speed and a 23% improvement in phase 1 speed. Many more significant increases in plotting speed are in the works.
- The proof of space document in chiapos has been updated to the new format and edited for clarity. Additionally GitHub actions now has the on demand ability to create the PDF version.
- Relic has upstreamed our changes required for the IETF BLS standard. We now build directly from the Relic repository for all but Windows and will be migrating Windows in the next release.
- Minor improvements to the Coloured Coin wallet were integrated in advance of an upcoming re-factor.
- Smart wallet backup was upgraded to encrypt and sign the contents of the backup.

### Fixed

- Proof of space plotting now correctly calculates the total working space used in the `-t` directory.
- `chia show -w` now displays a message when balances cannot be displayed instead of throwing an error. Thanks to @freddiecoleman for this fix!
- Fix issue with shutting down full node (full node processes remained open, and caused a spinner when launching Chia)
- Various code review alerts for comparing to a wider type in chiapos were fixed. Additionally, unused code was removed from chiapos
- Benchmarking has been re-enabled in bls-signatures.
- Various node security vulnerabilities were addressed.
- Updated keyring, various GitHub actions, colorlog, cbor2, and clvm_tools.

## [1.0beta9] aka Beta 1.9 - 2020-07-27

### Added

- See wallet balances in command line: `chia show -w`
- Retry opening invalid plots every 20 minutes (so you can copy a large plot into a plot directory.)
- We've added `chia keys sign` and `chia keys verify` to allow farmers to certify their ownership of keys.
- Windows BLS Signature library now uses libsodium for additional security.
- You can now backup and restore Smart Wallet metadata.
- Binary wheels for ARM64/aarch64 also build for python 3.7.
- See and remove plot directories from the UI and command line.
- You can now specify the memory buffer in UI.
- Optimized MPIR for Sandybridge and Ivybridge CPUs under Windows

### Changed

- `chia start wallet-server` changed to `chia start wallet`, for consistency.
- All data size units are clarified to displayed in GiB instead of GB (powers of 1024 instead of 1000.)
- Better error messages for restoring wallet from mnemonic.

### Fixed

- Fixed open_connection not being cancelled when node exits.
- Increase the robustness of node and wallet shutdown.
- Handle disconnection and reconnection of hard drives properly.
- Addressed pre-Haswell Windows signatures failing.
- MacOS, Linux x64, and Linux aarch64 were not correctly compiling libsodium in
the blspy/bls-signatures library.
- Removed outdated "200 plots" language from Plot tab.
- Fixed spelling error for "folder" on Plot tab.
- Various node dependency security vulnerabilities have been fixed.
- Request peers was not returning currently connected peers older than 1 day.
- Fixed timeout exception inheritance changes under python 3.8 (pull 13528)

### Deprecated

- Removed legacy scripts such as chia-stop-server, chia-restart-harvester, etc.

## [1.0beta8] aka Beta 1.8 - 2020-07-16

### Added

- We have released a new plot file format. We believe that plots made in this
format and with these IETF BLS keys will work without significant changes on
mainnet at launch.
- We now use [chacha8](https://cr.yp.to/chacha.html) and
[blake3](https://github.com/BLAKE3-team/BLAKE3) for proof of space instead of
the now deprecated AES methods. This should increase plotting speed and support
more processors.
- Plot refreshing happens during all new challenges and only new/modified files
are read.
- Updated [blspy](https://github.com/Chia-Network/bls-signatures) to use the
new [IETF standard for BLS signatures](https://tools.ietf.org/html/draft-irtf-cfrg-bls-signature-02).
- Added a faster VDF process which generates n-wesolowski proofs quickly
after the VDF result is known. This requires a high number of CPUs. To use it,
set timelord.fast_algorithm = True in the config file.
- Added a new type of timelord helper - blue boxes, which generate compact
proofs of time for existing proven blocks. This helps reducing the database
size and speeds up syncing a node for new users joining the network. Full nodes
send 100 random un-compact blocks per hour to blue boxes, and if
timelord.sanitizer_mode = True, the blue box timelord will work on those
challenges. Unlike the main timelord, average machines can run blue boxes
and contribute to the chain. Expect improvements to the install method for
blue boxes in future releases.
- From the UI you can add a directory that harvester will always check for
existing and new plots. Harvester will only look in the specific directory you
specify so you'll have to add any subfolders you want to also contain plots.
- The UI now asks for confirmation before closing and shows shutdown progress.
- UI now tries to shut down servers gracefully before exiting, and also closes
the daemon before starting.
- The various sub repositories (chiapos, chiavdf, etc.) now build ARM64 binary
wheels for Linux with Python 3.8. This makes installing on Ubuntu 20.04 lts on
a Raspberry Pi 3 or 4 easy.
- Ci's check to see if they have secret access and attempt to fail cleanly so
that ci runs successfully complete from PRs or forked repositories.
- Farmer now sends challenges after a handshake with harvester.
- The bls-signatures binary wheels include libsodium on all but Windows which
we expect to add in future releases.
- The chia executable is now available if installing from the Windows or MacOS
Graphical installer. Try `./chia -h` from
`~\AppData\Local\Chia-Blockchain\app-0.1.8\resources\app.asar.unpacked\daemon\`
in Windows or
`/Applications/Chia.app/Contents/Resources/app.asar.unpacked/daemon` on MacOS.

### Changed

- Minor changes have been made across the repositories to better support
compiling on OpenBSD. HT @n1000.
- Changed XCH units to TXCH units for testnet.
- A push to a branch will cancel all ci runs still running for that branch.
- Ci's now cache pip and npm caches between runs.
- Improve test speed with smaller discriminants, less blocks, less keys, and
smaller plots.
- RPC servers and clients were refactored.
- The keychain no longer supports old keys that don't have mnemonics.
- The keychain uses BIP39 for seed derivation, using the "" passphrase, and
also stores public keys.
- Plots.yaml has been replaced.  Plot secret keys are stored in the plots,
 and a list of directories that harvester can find plots in are in config.yaml.
You can move plots around to any directory in config.yaml as long as the farmer
has the correct farmer's secret key too.
- Auto scanning of plot directories for .plot files.
- The block header format was changed (puzzle hashes and pool signature).
- Coinbase and fees coin are now in merkle set, and bip158 filter.
- New harvester protocol with 2/2 harvester and farmer signatures, and modified
farmer and full node protocols.
- 255/256 filter which allows virtually unlimited plots per harvester or drive.
- Improved create_plots and check_plots scripts, which are now
"chia plots create" and "chia plots check".
- Add plot directories to config.yaml from the cli with "chia plots add".
- Use real plot sizes in UI instead of a formula/
- HD keys now use EIP 2333 format instead of BIP32, for compatibility with
other chains.
- Keys are now derived with the EIP 2334 (m/12381/8444/a/b).
- Removed the ability to pass in sk_seed to plotting, to increase security.
- Linux builds of chiavdf and blspy now use a fresh build of gmp 6.2.1.

### Fixed

- uPnP now works on Windows.
- Log rotation should now properly rotate every 20MB and keep 7 historical logs.
- Node had a significant memory leak under load due to an extraneous fork
in the network code.
- Skylake processors on Windows without AVX would fail to run.
- Harvester no longer runs into 512 maximum file handles open issue on Windows.
- The version generator for new installers incorrectly handled the "dev"
versions after a release tag.
- Due to a python bug, ssl connections could randomly fail. Worked around
[Python issue 29288](https://bugs.python.org/issue29288)
- Removed websocket max message limit, allowing for more plots
- Daemon was crashing when websocket gets improperly closed

### Deprecated

- All keys generated before Beta 1.8 are of an old format and no longer useful.
- All plots generated before Beta 1.8 are no longer compatible with testnet and
should be deleted.

### Known Issues

- For Windows users on pre Haswell CPUs there is a known issue that causes
"Given G1 element failed g1_is_valid check" when attempting to generate
keys. This is a regression from our previous fix when it was upstreamed into
relic. We will make a patch available for these systems shortly.

## [1.0beta7] aka Beta 1.7 - 2020-06-08

### Added

- Added ability to add plot from filesystem (you will need pool_pk and sk from plots.yaml.)
- Added ability to import private keys in the UI.
- Added ability to see private keys and mnemonic seeds in the keys menu
- User can specify log level in the config file (defaults to info.)
- The Windows installer is now signed by a Chia Network certificate. It may take some time to develop enough reputation to not warn multiple times during install.

### Changed

- Plots are now refreshed in the UI after each plot instead of at the end of plotting.
- We have made performance improvements to plotting speed on all platforms.
- The command line plotter now supports specifying it's memory buffer size.
- Test plots for the simulation and testing harness now go into `~/.chia/test-plots/`
- We have completely refactored all networking code towards making each Chia service use the same default networking infrastructure and move to websockets as the default networking wire protocol.
- We added additional improvements and more RPCs to the start daemon and various services to continue to make chia start/stop reliable cross platform.
- The install.sh script now discovers if it's running on Ubuntu less than 20.04 and correctly upgrades node.js to the current stable version.
- For GitHub ci builds of the Windows installer, editbin.exe is more reliably found.
- All installer ci builds now obtain version information automatically from setuptools_scm and convert it to an installer version number that is appropriate for the platform and type of release (dev versus release.)
- We now codesign the Apple .dmg installer with the Chia Network developer ID on both GitHub Actions and Azure Pipelines. We will be notarizing and distributing the Azure Pipelines version as it's built on MacOS Mojave (10.14.6) for stronger cross version support.

### Fixed

- Having spaces in the path to a plot or temporary directory caused plotting to fail.
- Changing keys will no longer interrupt plotting log.
- 1.6 introduced a bug where certain very many core machines would sync the blockchain very slowly.
- The plotter log in the UI should scroll more reliably.
- The plotter UI should display the correct log on all platforms
- Starting chia now waits for the full node to be active before contacting the introducer.

## [1.0beta6] aka Beta 1.6 - 2020-06-01

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
- `chia-check-plots` now does not override plots.yaml, which means concurrent plots will properly be added to plots.yaml.
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

### Changed

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

### Changed

- `chia-restart-harvester` has been renamed from `chia-start-harvester` to better reflect its functionality. Use it to restart a harvester that's farming so that it will pick up newly finished plots.
- We made the Wallet configurable to connect to a remote trusted node.
- We now have farmers reconnect to their trusted node if they lose contact.
- We updated our miniupnpc dependency to version 2.1.
- We increase the default farmer propagate threshold to reduce chain stall probability.

### Deprecated

- You should not copy over any prior Wallet database as they are not compatible with Beta3. Your existing full node will not have to re-sync and its database remains compatible.

#### Fixed

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

- There is now full transaction support on the Chia blockchain. In this initial Beta 1.0 release, all transaction types are supported though the wallets and UIs currently only directly support basic transactions like coinbase rewards and sending coins while paying fees. UI support for our [smart transactions](https://github.com/Chia-Network/wallets/blob/main/README.md) will be available in the UIs shortly.
- Wallet and Node GUI’s are available on Windows, Mac, and desktop Linux platforms. We now use an Electron UI that is a full light client wallet that can also serve as a node UI. Our Windows Electron Wallet can run standalone by connecting to other nodes on the network or another node you run. WSL 2 on Windows can run everything except the Wallet but you can run the Wallet on the native Windows side of the same machine. Also the WSL 2 install process is 3 times faster and _much_ easier. Windows native node/farmer/plotting functionality are coming soon.
- Install is significantly easier with less dependencies on all supported platforms.
- If you’re a farmer you can use the Wallet to keep track of your earnings. Either use the same keys.yaml on the same machine or copy the keys.yaml to another machine where you want to track of and spend your coins.
- We have continued to make improvements to the speed of VDF squaring, creating a VDF proof, and verifying a VDF proof.

### Changed

- We have revamped the chia management command line. To start a farmer all you have to do is start the venv with `. ./activate` and then type `chia-start-farmer &`. The [README.md](https://github.com/Chia-Network/chia-blockchain/blob/main/README.md) has been updated to reflect the new commands.
- We have moved all node to node communication to TLS 1.3 by default. For now, all TLS is unauthenticated but certain types of over the wire node to node communications will have the ability to authenticate both by certificate and by inter protocol signature. Encrypting over the wire by default stops casual snooping of transaction origination, light wallet to trusted node communication, and harvester-farmer-node communication for example. This leaves only the mempool and the chain itself open to casual observation by the public and the various entities around the world.
- Configuration directories have been moved to a default location of HomeDirectory/.chia/release/config, plots/ db/, wallet/ etc. This can be overridden by `export CHIA_ROOT=~/.chia` for example which would then put the plots directory in `HomeDirectory/.chia/plots`.
- The libraries chia-pos, chia-fast-vdf, and chia-bip-158 have been moved to their own repositories: [chiapos](https://github.com/Chia-Network/chiapos), [chiavdf](https://github.com/Chia-Network/chiavdf), and [chaibip158](https://github.com/Chia-Network/chiabip158). They are brought in by chia-blockchain at install time. Our BLS signature library remains at [bls-signatures](https://github.com/Chia-Network/bls-signatures).
- The install process now brings in chiapos, chiavdf, etc from Pypi where they are auto published via GitHub Actions ci using cibuildwheel. Check out `.github/workflows/build.yml` for build methods in each of the sub repositories.
- `chia-regenerate-keys` has been renamed `chia-generate-keys`.
- setproctitle is now an optional install dependency that we will continue to install in the default install methods.
- The project now defaults to `venv` without the proceeding . to better match best practices.
- Developer requirements were separated from the actual requirements.
- `install-timelord.sh` has been pulled out from `install.sh`. This script downloads the source python package for chiavdf and compiles it locally for timelords. vdf_client can be included or excluded to make building normal user wheels easier.

### Removed

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
- New AJAX based full node UI. To access go to [http://127.0.0.1:8555/index.html](http://127.0.0.1:8555/index.html) with any modern web browser on the same machine as the full node.
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
- More details on the release at [https://www.chia.net/developer/](https://www.chia.net/developer/)

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
