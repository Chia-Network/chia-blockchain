# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project does not yet adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for setuptools_scm/PEP 440 reasons.

## 1.1.1 Chia Blockchain 2021-04-21

### Added

- This is a bug fix release for 1.1.0. It is not required to upgrade from 1.1.0 if you are not experiencing the specific issue that it addresses. You are required to upgrade from any 1.0.x version before Monday evening PDT to continue farming.

### Changed

- Logging now includes year, month, and date. Thanks and apologies for not tipping the hat sooner to @alfonsoperez for the PR.

### Fixed

- Changes were made in 1.1.0 to make sure that even out of order signage points were found and responded to by as many farmers as possible. That change lead to a situation where the harvester could thrash on the same cached signage point.

## 1.1.0 Chia Blockchain 2021-04-21

### Added

- This fork release includes full transaction support for the Chia Blockchain. Transactions are still disabled until 5/3/2021 at 10:00AM PDT. It is hard to overstate how much work and clean up went into this release.
- This is the 1.0 release of Chialisp. Much has been massaged and finalized. We will be putting a focus on updating and expanding the documentation on [chialisp.com](https://chialisp.com) shortly.
- Farmers now compress blocks using code snippets from previous blocks. This saves storage space and allows larger smart coins to have a library of sorts on chain.
- We now support offline signing of coins.
- You can now ask for an offset wallet receive address in the cli. Thanks @jespino.
- When adding plots we attempt to detect a duplicate and not load it.

### Changed

- We have changed how transactions will unlock from a blockheight to a timestamp. As noted above that timestamp is 5/3/2021 at 10AM PDT.
- We have temporarily disabled the "Delete Plots" button in the Windows GUI as we are still working on debugging upstream issues that are causing it.
- There are various optimizations in node and wallet to increase sync speed and lower work to stay in sync. We expect to add additional significant performance improvements in the next release also.
- Transactions now add the agg_sig_me of the genesis block for chain compatibility reasons.
- Wallet is far less chatty to unload the classic introducers. DNS introducers will be coming shortly to replace the classic introducers that are still deployed.
- Netspace is now calculated across the previous 4068 blocks (generally the past 24 hours) in the GUI and cli.

### Fixed

- Performance of streamable has been increased, which should help the full node use less CPU - especially when syncing.
- Timelords are now successfully infusing almost 100% of blocks.
- Harvester should be a bit more tolerant of some bad plots.

## 1.0.5 Chia Blockchain 2021-04-14

### Added

- This is a maintenance release for 1.0.4 to fix a few mostly cosmetic issues. Please refer to the 1.0.4 notes for the substantive plotting changes - for example - in that release.

### Changed

- The GUI now calls it an Estimated Time to Win and has enhanced explanations in the tool tip that the estimated time is often not be the actual time. We have some additional improvements we plan to make here in future releases.
- Development installers now handle semver development versions correctly.

### Fixed

- Temp space sizes needed for k = 33 and higher were accidentally under-reported. The values we have placed into the GUI may be conservative in being too large and appreciate feedback from the community on the new optimal temp space needed and RAM choices.
- The GUI plotting progress bar was reaching 100% too early. Thanks to @davidbb for the PR.
- Help -> About was blank.
- Our estimate for k=32 was about 0.4GiB too low in some cases.
- Building the GUI in especially ARM64 Linux was painful enough to be considered broken.
## 1.0.4 Chia Blockchain 2021-04-12

### Added

- Starting approximately April 21, 2021, the GUI will notify you that this version will stop working at block height 193,536 and will persistently warn you from that block on that you can not use this version (or any earlier version) to farm. This is to support the upgrade to the transaction fork.
- We now have translations for Brazilian Portuguese, Australian English, and Pirate. Thanks to @fsavaget, @darkflare, @maahhh, @harold_257, @kontin, and @GunnlaugurCalvi. Yarr - don't be losing your 24 word treasure map...

### Changed

- The plotter in bitfield mode is much improved in plotting speed (~15% faster than in 1.0.3), now requires 28% less temporary space (238.3 GiB/256 GB), and now uses its maximum memory in phase 1 and only needs 3389MiB for optimal sorting of a k32. Total writes should also be down by about 20%. On almost all machines we expect bitfield to be as fast or faster. For CPUs that predate the [Nehalem architecture](https://en.wikipedia.org/wiki/Nehalem_(microarchitecture)), bitfield plotting will not work and you will need to use no bitfield. Those CPUs were generally designed before 2010.
- The `src` directory in chia-blockchain has been changed to `chia` to avoid namespace collisions.
- GUI install builds have been simplified to rely on one `.spec` file in `chia/`
- The weight proof timeout can now be configured in config.yaml.
- Peer discovery is now retried more often after you receive initial peers.

### Fixed

- We have made significant improvements and bug fixes to stop blockchain and wallet database corruption issues.
- We now pass the environment into the Daemon and this should solve some Windows and MacOS startup bugs.
- The ARM64 .deb installer will now work well on Raspberry Pi OS 64 bit and Ubuntu 18.04 LTS or newer.
- We have made improvements in weight proof generation and saving.
- Wallet start up would have a race condition that output a harmless error on startup.
- Thanks for a typo fix from @alfonsoperez.

## 1.0.3 Chia Blockchain 2021-03-30

### Added

- This is a minor bug fix release for version 1.0.2
- You should review the [release notes for v1.0.2](https://github.com/Chia-Network/chia-blockchain/releases/tag/1.0.2) but we especially want to point out that wallet sync is much faster than in 1.0.1 and earlier versions.

### Fixed

- An incorrect merge brought in unreleased features and broke `chia keys`.
- Omitted from the 1.0.2 changelog, we fixed one crash in harvester with the release of chiapos 1.0.0 as well.

## 1.0.2 Chia Blockchain 2021-03-30

### Added

- We have released version 1.0.0 of [chiapos](https://github.com/Chia-Network/chiapos). This includes a 20% speed increase for bitfield plotting compared to the previous version on the same machine. In many cases this will mean that bitfield plotting is as fast or faster than non bitfield plotting.
- @xorinox improved our support for RedHat related distributions in `install.sh`.
- @ayaseen improved our support for RedHat related distributions in `install-timelord.sh`.
- We have added Dutch and Polish to supported translations. Thanks @psydafke, @WesleyVH, @pieterhauwaerts, @bartlomiej.tokarzewski, @abstruso, @feel.the.code, and @Axadiw for contributions to [translations on Crowdin](https://crowdin.com/project/chia-blockchain).
- The GUI now supports "Exclude final directory" when plotting. This is found in the Advanced Options for step 2 on the plot creation page.

### Changed

- Wallet now uses a trusted node and, when syncing from that node, Wallet does not do as many validations.
- @jespino changed `chia keys show` to require the `--show-mnemonic-seed` before it displays your 24 work private key mnemonic.
- We decreased the size of the block cache in node to perform better with longer chains.
- You can now add a private key mnemonic from a file with `chia keys show`.
- @Flofie caught an error in CONTRIBUTING.md.
- We no longer rely on aiter so it has been removed.
- Keyring deprecated the use of OS_X in favor of MacOS.
- "Broken pipe" error was decreased to a warning.
- Many non critical log messages were decreased from warning to info log level.
- Harvester should now log the plot file name if it finds a bad plot at error log level.

### Fixed

- Peer ips were being written to the database on a per ip basis. This caused a lot of wasted disk activity and was costing full node performance.
- We fixed an issue where the last block wasn't fetched by the GUI.
- There was an edge case with full node store that can stall syncing.
- There was a potential node locking issue that could have prevented a Timelord from getting a new peak and cause a chain stall.
- We did not correctly support some Crowdin locales. Pirate English was starting to overwrite US English for example.

## 1.0.1 Chia Blockchain 2021-03-23

### Added

- There is now a simple progress bar on the GUI Plot page and when you view the log from the three dots on the right.
- Users must now explicitly set the `--show-mnemonic-seed` flag to see their private keys when running `chia keys show`.
- We are now building Linux GUI installers. These should be considered beta quality for now.
- Translations now available for German, Traditional Chinese, and Danish. Thanks to @Dravenex, @MaestroOnICe, @loudsyncro, @loppefaaret, @thirteenthd, @wong8888, @N418, and @swjz for all the translation help. You to can translate at our [Crowdin project](https://crowdin.com/project/chia-blockchain/).

### Changed

- The mainnet genesis is now in the initial config.yaml and the green flag components have been removed.
- Our release process and branching strategy has changed. CONTRIBUTING.md will be updated in the main branch soon with details.
- This mainnet release does not migrate previous testnet configuration files.

### Fixed

- Weight proofs, especially wallet weight proofs were failing when some Blueboxed proofs of time were encountered.
- Users can now pip install e.g. chia-blockchain==1.0.1 on most platforms.
- Sometimes the GUI had an error regarding MainWindow.

## 1.0.0 First Release of Chia Blockchain 2021-03-17

### Added

- This is the first production release of the Chia Blockchain. This can be installed and will wait for the green flag that will be dropped at approximately 7AM PDST (14:00 UTC) on Friday March 19, 2021. All farming rewards from that point forward will be considered valid and valuable XCH. There is a six week lock on all transactions. During those six weeks farmers will be earning their farming rewards but those rewards can not be spent.
- Initial difficulty will be set for 100PB. This may mean the initial epoch may be slow. Mainnet difficulty resets are targeted for 24 hours so this difficulty will adjust to the actual space brought online in 24 to 48 hours after launch.
- Transactions are not enabled in the 1.0.0 version and will be soft forked in during the six week period via a 1.1.0 release.
- There will also be a 1.0.1 release after the green flag process is complete to simplify install for new users by removing the green flag alert. In the interim there will be new testnet releases using the 1.1bx version scheme.
- Starting with release 1.0.0 you usually no longer need to upgrade and 1.0.1 will be fully optional. However you will have to upgrade to 1.1 after it is out and before the six week period ends. We plan to give plenty of time between those two events up to and including pushing back the transaction start date by a short period of time.
- Thank you to @L3Sota for adding a Japanese translation via our [Crowdin project](https://crowdin.com/project/chia-blockchain).
- The generation of CoinIDs is now unique on mainnet to avoid testnet transaction replays.
- Validation of transactions will now fail after the expiration of the six week period.

### Changed

- Weight proof request timeout was increased to 180 seconds.
- Mainnet uses port 8444 and other constants and service names were changed for mainnet.
- GUI locales are now extracted and compiled in `npm run build`.
- Daemon now logs to STDERR also.

### Fixed

- GUI plotting on some Macs was not working due to locale issues with Click.
- Thank you @L3Sota for bringing this log back into 2021.
- The errant warning on Electron startup has been removed. Thanks @dkackman.


## 1.0rc9 aka Release Candidate 9 - 2021-03-16

### Changed
- This is a hard fork/breaking change from RC6/7/8. The current plan is to drop the flag at noon pacific time, today 3/16.
- Using the real prefarm keys for this test

### Fixed
- Found and fixed another green flag related issue
- Fixed an issue with weight proofs where all sub-epochs were sampled, and the size of the weight proof kept growing
- Fixed an issue with install-gui.sh, where npm audit fix was failing. (Thanks @Depado!)
- Migration with CHIA_ROOT set does not crash chia init

## 1.0rc8 aka Release Candidate 8 - 2021-03-15

### Added

- This is a hard fork/breaking change from RC6/7. TXCH Coins will **not** be moved forward but your plots and keys and parts of your configuration do. When you install this version before 10AM PDST on 3/16/2021 it will load up, start finding peers, and otherwise wait for the flag drop at that time to start farming. This is likely to be the last dress rehearsal for mainnet launch. Our [3/15/2021 blog post](https://www.chia.net/2021/03/15/mainnet-update.html) has more details on the current mainnet launch plan.
- The GUI now has a tooltip that directs users to the explanation of the plot filter.
- The GUI now has a tooltip to explain the "Disable bitfield plotting" option. Thanks @shaneo257 for the idea.
- The GUI now has a tooltip to explain Hierarchical Deterministic keys next to Receive Address on the Wallet page.

### Changed

- We now use Python 3.9 to build MacOS installers.
- Harvester now catches another error class and continues to harvest. Thanks to @xorinox for this PR.
- We now use a smaller weight proof sample size to ease the load on smaller machines when syncing.
- Starting the GUI from Linux will now also error out if `npm run build` is run outside the venv. Huge thanks to @dkackman for that PR.
- `chia farm summary` will now display TXCH or XCH as appropriate.
- We added more time to our API timeouts and improved logging around times outs.

### Fixed

- We no longer use the transaction cache to look up transactions for new transactions as that was causing a wallet sync bug.
- Sometimes the GUI would not pick up the fingerprint for the plotting key.
- `chia farm summary` displayed some incorrect amounts.
- Weight proofs were timing out.
- Changes to farming rewards target addresses from the GUI were not being saved for restart correctly.
- Signage points, recent deficit blocks, and slots for overflow challenge blocks had minor issues.

## 1.0rc7 aka Release Candidate 7 - 2021-03-13

### Changed

- Our green flag test blockchain launch worked but it uncovered a flaw in our installer versions. This release is a bug fix release to address that flaw. You should read the RC6 changes below if this is your first time installing since RC5.
- Thanks to @dkackman for implementing an early exit of the GUI if you run `npm run build` without being in the `venv`.
- `chia netspace` now defaults to 1000 blocks to mirror the GUI.
- The installer build process was spruced up some.

### Fixed

- Setting difficulty way too low on the testnet_6 launch revealed a Timelord edge case. The full node was hardcoding the default difficulty if block height is < EPOCH_BLOCKS. However there were many overlapping blocks, so none of the blocks reached the height, and therefore the timelord infused the wrong difficulty.
- Fixed a race condition in the Timelord, where it took time to update the state, so it ignored the new_peak_timelord form the full_node, which should have reset the timelord to a good state.
- Wallet notoriously showed "not synced" when it was in sync.
- Installers were not correctly placing root TLS certificates into the bundle.
- Weight proofs had a logic typo.
- There was a typo in `chia netspace`. Thanks @altendky.
- There was a typo in `chia plots`. Thanks @adamfiddler.

### Known Issues

- Some users can't plot in the GUI in MacOS Big Sur - especially on M1. See issue [1189](https://github.com/Chia-Network/chia-blockchain/issues/1189)

## 1.0rc6 aka Release Candidate 6 - 2021-03-11

### Added

- This is a hard fork/breaking change from RC5. TXCH Coins will **not** be moved forward but your plots and keys and parts of your configuration do. We will be testing the final mainnet release strategy with the launch of RC6. For the test, those who are comfortable running the dev branch will update and start up their farms. All harvesters and plots will load and until the green flag drops, peers will be gossiped so your farm can establish good network connectivity. When the flag drops, each node will pull down the signed genesis challenge and start farming. Block 1 will be broadcast to anyone who hasn't seen the flag drop yet. The only difference for mainnet is that there will be 1.0 installers and a main branch release more than 24 hours before the real green flag.
- There is now basic plot queueing functionality in the GUI. By default, plotting works as it has in the past. However you can now name a queue in Step 2 Advanced Options. Chose something like `first`. Everything you add to the `first` queue will start up like it has in the past but now you can go through the steps again and create a queue named `second` and it will immediately start plotting as if it is unaware of and parallel with `first`. A great use case is that you would set `first` to plot 5 plots sequentially and then you'd set `second` to plot 5 sequentially and that would give you two parallel queues of 5 plot's each. We will be returning to plotting speed and UI soon. Thanks @jespino for this clever work around for now.
- There is now an option on the Farm page to manage your farming rewards receive addresses. This makes it easy to send your farming rewards to an offline wallet. This also checks your existing rewards addresses and warns if you do not have the matching private key. That is expected if you are using an offline wallet of course.
- Functionally has been added to the farmer rpc including checking and changing your farming rewards target addresses.
- Added the ability to translate material-ui components like `Row 1 of 10`. Thanks @jespino.
- Arch linux support has been added to `sh install.sh`. Thanks @jespino.
- Update FullBlock to Allow Generator References - a list of block heights of generators to be made available to the block program of the current block at generator runtime. This sets the stage for smart coins calling existing "libraries" already on the chain to lower fees and increase the scale of complex smart coins.

## Changed

- Remove `chia plots "-s" "--stripe_size"` and the strip size setting in the Advanced section of the GUI. We now always use the best default of 64K for the GUI and cli.
- `chia keys add` takes secret words a prompt on the command line or stdin instead of command line arguments for security.
- Version 1.0.1 of chiavdf was added. This brought MPIR on Windows to the most recent release. Additionally we removed inefficient ConvertIntegerToBytes() and ConvertBytesToInt() functions, use GMP library's mpz_export/mpz_import for big integers and simple helper functions for built-in integer types. The latter are taken from chiavdf. We now require compressed forms to be encoded canonically when deserializing. This should prevent potential grinding attacks where some non-canonical encodings of a compressed form could be used to change its hash and thus the next challenges derived from it. Canonically encoded compressed forms must be reduced and must produce the same string when deserialized and serialized again.
- Version 1.0 of our BLS signature library is included. We brought Relic, gmp and MPIR up to their most recent releases. We again thank the Dash team for their fixes and improvements.
- We now hand build Apple Silicon native binary wheels for all chia-blockchain dependencies and host them at [https://pypi.chia.net/simple](https://pypi.chia.net/simple). We are likely to hand build a MacOS ARM64 dmg available and certainly will for 1.0. You can install natively on M1 now with the `git clone` developer method today. Just make sure Python 3.9 is installed. `python3 --version` works.
- The GUI now shows you which network you are connected to on the Full Node page. It will also wait patiently for the green flag to drop on a network launch.
- In the GUI you can only plot k=32 or larger with the single exception of k=25 for testing. You will have to confirm choosing k=25 however. Thanks to @jespino for help on this and limiting the cli as well.
- The restore smart wallets from backup prompt has been improved to better get the intent across and that it can be skipped.
- At the top of the plotting wizard we have added text pointing out that you can plot without being in sync or on the internet.
- Wallet no longer automatically creates a new hierarchical deterministic wallet receive address on each start. You can and still should choose a new one with the `NEW ADDRESS` button for each new transaction for privacy.
- The network maximum k size is now set to k=50. We think that may be more storage than atoms in the solar system so it should be ok. But we will probably be hated for it in 200 years...
- The formula for computing iterations is simplified, so that only one division is necessary, and inverting the (1-x) into just x.
- There are new timestamp consensus rules. A block N must have a greater timestamp than block N-1. Also, a block's timestamp cannot be more than 5 minutes in the future. Note that we have decided that work factor difficulty resets are now going to be 24 hours on mainnet but are still shorter on testnet.
- A List[Tuple[uint16, str]] is added to the peer network handshake. These are the capabilities that the node supports, to add new features to the protocol in an easy - soft fork - manner. The message_id is now before the data in each message.
- Peer gossip limits were set.
- Generators have been re-worked in CLVM. We added a chialisp deserialization puzzle and improved the low-level generator. We reduce the accepted atom size to 1MB during ChiaLisp native deserialization.
- When processing mempool transactions, Coin IDs are now calculated from parent coin ID and amount
- We implemented rate limiting for full node. This can and will lead to short term bans of certain peers that didn't behave in expected ways. This is ok and normal, but strong defense against many DDOS attacks.
- `requirements-dev.txt` has been removed in favor of the CI actions and test scripts.
- We have moved to a new and much higher scalability download.chia.net to support the mainnet launch flag and additional download demand.
- To always get the latest testnet and then mainnet installers you can now use a latest URL: [Windows](https://download.chia.net/latest/Setup-Win64.exe) and [MacOS x86_64](https://download.chia.net/latest/Setup-MacOS.dmg).
- Chia wheels not on Pypi and some dependecies not found there also are now on pypi.chia.net.
- Additional typing has been added to the Python code with thanks to @jespino.
- Cryptography and Keyring have been bumped to their current releases.
- PRs and commits to the chia-blockchain-gui repository will automatically have their locales updated.

## Fixed

- The Farm page will now no longer get stuck at 50 TXCH farmed.
- `chia farm` has had multiple bugs and spelling issues addressed. Thanks to @alfonsoperez, @soulmerge and @olivernyc for your contributions.
- `chia wallet` had various bugs.
- Various weight proof improvements.
- Some users on Big Sur could not plot from the GUI as the log window would be stuck on "Loading."
- We believe we have fixed the chain stall/confused Timelord bug from ~ 13:00 UTC 3/10/21. We've added additional recovery logic as well.
- Logs from receiving a duplicate compacted Proof of Time are much more human friendly.
- We believe that the install/migrate process was bringing forward bad farming rewards receive addresses. We have attempted to stop that by only migrating RC3 and newer configurations. You can make sure you are not effected by using the Manage Farming Rewards tool mentioned above or putting a known good wallet receive address in both `xch_target_address` sections of config.yaml.
- Wallet cached transactions incorrectly in some cases.

## 1.0rc5 aka Release Candidate 5 - 2021-03-04

### Added

- The RC5 release is a new breaking change/hard fork blockchain. Plots and keys from previous chains will work fine on RC5 but balances of TXCH will not come forward.
- We now support a "green flag" chain launch process. A new version of the software will poll download.chia.net/notify/ for a signed json file that will be the genesis block of the chain for that version. This will allow unattended start at mainnet.
- Bluebox Timelords are back. These are Timelords most anyone can run. They search through the historical chain and find large proofs of times and compact them down to their smallest representation. This significantly speeds up syncing for newly started nodes. Currently this is only supported on Linux and MacOS x86_64 but we will expand that. Any desktop or server of any age will be fast enough to be a useful Bluebox Timelord.
- Thanks to @jespino there is now `chia farm summary`. You can now get almost exactly the same farming information on the CLI as the GUI.
- We have added Romanian to the GUI translations. Thank you to @bicilis on [Crowdin](https://crowdin.com/project/chia-blockchain). We also added a couple of additional target languages. Klingon anyone?
- `chia wallet` now takes get_address to get a new wallet receive address from the CLI.
- `chia plots check` will list out all the failed plot filenames at the end of the report. Thanks for the PR go to @eFishCent.
- Chialisp and the clvm have had the standard puzzle updated and we replaced `((c P A))` with `(a P A)`.

## Changed

- Testnets and mainnet now set their minimum `k` size and enforce it. RC5 testnet will reject plots of size less than k=32.
- Sub slots now require 16 blocks instead of 12.
- Thanks to @xdustinface of Dash, the BlS Signature library has been updated to 0.9 with clean ups and some speed ups. This changed how the G2 infinity element was handled and we now manage it inside of chia-blockchain, etc., instead of in blspy.
- We have updated the display of peer nodes and moved adding a peer to it's own pop up in the GUI.
- Block searching in the GUI has been improved.
- @jespino added i18n support and refactored how locales are loaded in the GUI. Additionally he moved more strings into the translation infrastructure for translators.
- In chiavdf we changed n-Wesolowski proofs to include B instead of y in segments. Proof segments now have the form (iters, B, proof) instead of (iters, y, proof). This reduces proof segment size from 208 to 141 bytes.
- The new chiavdf proof format is not compatible with the old one, however zero-Wesolowski proofs are not affected as they have zero proof segments and consist only of (y, proof).
- We made two HashPrime optimizations in chiavdf. This forces numbers being tested for primality to be odd and avoids an unnecessary update of the sprout vector by stopping after the first non-zero value. This is a breaking change as it changes the prime numbers generated from a given seed. We believe this is the final breaking change for chiavdf.
- chiabip158 was set to a gold 1.0 version.
- Comments to Chialisp and clvm source have been updated for all of the Chialisp changes over the proceeding three weeks.
- And thanks yet again to @jespino for a host of PRs to add more detailed typing to various components in chia-blockchain.
- aiohttp was updated to 3.7.4 to address a low severity [security issue](https://github.com/advisories/GHSA-v6wp-4m6f-gcjg).
- calccrypto/uint128_t was updated in the Windows chiapos implementation. Chiapos required some changes its build process to support MacOS ARM64.

### Fixed

- Harvester would crash if it encountered more than 16,000 plot files or 256 directories.
- Nodes that were interrupted by a network crash or standby on a laptop were not syncing upon reconnection in RC4.
- Sync issues could stop syncing from restarting and could lead to a peer host that you could not remove.
- Adding Click changed the behavior of `chia keys add -m`. The help now makes it clear that the 24 word mnemonic needs to be surrounded by a pair of quotes.
- Python root CA certificates have issues so we have added the Mozilla certificate store via curl.se and use that to connect to backup.chia.net via https, for example.
- The difficulty adjustment calculation was simplified.
- All of the chia sub repositories that were attempting to build MacOS Universal wheels were only generating x86_64 wheels internally. We have moved back to only generating x86_64 MacOS wheels on CI.
- However, we have updated and test compiled all Chia dependencies on Apple Silicon and will be making available a test .dmg for MacOS ARM64 shortly.
- Various weight proof edge cases have been fixed.
- Various typos and style clean ups were made to the Click CLI implementation. `chia -upnp f` was added to disable uPnP.
- `chia plots check` shouldn't crash when encountering plots that cause RuntimeError. PR again thanks to @eFishCent.
- Coloured coin announcements had a bug that would allow counterfeiting.

## 1.0rc4 aka Release Candidate 4 - 2021-02-25

### Fixed

- This is a bug fix release for RC3. There was an unexpected interaction between the GUI and the Click cli tool regarding Windows that made GUI plotting not start on all GUIs.

## 1.0rc3 aka Release Candidate 3 - 2021-02-25

### Added

- RC3 is a new chain to support the last major chialisp changes. TXCH from the RC1/2 chain do not come forward to this chain but plots and keys continue to work as usual.
- We have lowered the transaction lock to the first 5000 blocks to facilitate testing. We also started this chain at a lower difficulty.
- A new RPC api: /push_tx. Using this RPC, you can spend custom chialisp programs. You need to make a SpendBundle, which includes the puzzle reveal (chialisp), a solution (chialisp) and a signature.
- You can now use the RPC apis to query the mempool.
- There are now Swedish, Spanish, and Slovak translations. Huge thanks to @ordtrogen (Swedish), @jespino and @dvd101x (Spanish), and our own @seeden (Slovak). Also thanks were due to @f00b4r (Finnish), @A-Caccese (Italian), and @Bibop182 and @LeonidShamis (Russian). Quite a few more are almost complete and ready for inclusion. You can help translate and review translations at our [crowdin project](https://crowdin.com/project/chia-blockchain).
- You can obtain a new wallet receive address on the command line with `chia wallet new_address`. Thanks to @jespino for this and a lot more in the next section below.
- You will now see Your Harvester Network in the GUI even if you have no plots.

### Changed

- All chialisp opcodes have been renumbered. This should be the last major breaking change for chialisp and the clvm. There are a couple minor enhancements still needed for mainnet launch, but they may or may not require minor breaking changes. We will be restarting testnet chains on a mostly weekly basis either way.
- Node batch syncing performance was increased, and it now avoids re-validating blocks that node had already validated.
- The entire CLI has been ported to [Click](https://click.palletsprojects.com/en/7.x/). Huge thanks to @jespino for the big assist and @unparalleled-js for the [recommendation and the initial start](https://github.com/Chia-Network/chia-blockchain/issues/464). This will make building out the CLI much easier. There are some subtle changes and some shortcuts are not there anymore. `chia -h` and `chia SUBCOMMAND -h` can be your guide.
- We have upgraded Electron to 11.3 to support Apple Silicon. There are still one or two issues in our build chain for Apple Silicon but we should have an M1 native build shortly.
- The websocket address is no longer displayed in the GUI unless it is running as a remote GUI. Thanks @dkackman !
- `chia plots check` now will continue checking after it finds an error in a plot to the total number of checks you specified.
- If you run install-gui.sh or install-timelord.sh without being in the venv, the script will warn you that you need to `. ./activate` and exit with error.
- If you attempt to install on a 32 bit Pi/ARM OS, the installer exits with a helpful error message. You  can still fail when running under a 64 bit kernel but using a 32 bit Python 3.
- The application is now more aware of whether it is running a testnet or mainnet. This impacts wallet's display behavior and certain blockchain validation rules.
- Interface improvements for `chia netspace`.
- Now that aiosqlite included our upstream improvements we install version 0.17.0.
- `chia init` only migrates release candidate directories. The versioned sub directories under `~/chia` will be going away before mainnet.

### Fixed

- The GUI was often getting stuck on connecting to wallet. We beleive we have resolved this.
- We identified and fixed an issue where harvester would crash, especially when loading plots or checking a large amount of plots.
- The software now reports not synced in the GUI if not synced or being behind by 7 minutes or more.
- Difficulty was set too high for the RC1/2 chain. This lead to odd rewards behaviour as well as difficulty artificially could not fall as low as it should.
- Don't load plots that don't need to be loaded.
- We made various fixes and changes to weight proofs.
- Some configuration values were improperly ignored in migrations.
- Some debug logging was accidentally left in.
- `chia configure -log-level` was broken.
- We believe we finally have the Windows Installer obtaining the correct version information at build time.
- The application was sometimes not cancel pending items when closing certain websockets.
- Fixed filter hash and generator validation.
- Recursive replace was being called from the test suite.

## 1.0rc2 aka Release Candidate 2 - 2021-02-18

### Fixed

- This is an errata release for Release Candidate 1. There were a couple of things that did not smoothly migrate from the Beta versions. Please make sure you also consult the [release notes for RC-1](https://github.com/Chia-Network/chia-blockchain/releases/tag/1.0rc1) was well.
- Incorrect older spend to addresses were being migrated from Beta 27. This would send farming rewards to un-spendable coins.
- Netspace was not calculating properly in RC-1.
- The Windows installer was building with the wrong version number.
- @eFishCent didn't get correct credit in the RC 1 release notes. They have been updated below to be correct.

## 1.0rc1 aka Release Candidate 1 - 2021-02-18

### Added

- This is the first release in our release candidate series. There are still a few things that will change at the edges but the blockchain, clvm, and chialisp are in release form. We have one major change to chialisp/clvm that we have chosen to schedule for the next release as in this release we're breaking the way q/quote works. We also have one more revision to the VDF that will decrease the sizes of the proofs of time. We expect a few more releases in the release candidate series.
- Installers will now be of the pattern ChiaSetup-0.2.1.exe. `0.2` is release candidate and the final `.1` is the first release candidate.
- Use 'chia wallet get_transactions' in the command line to see your transactions.
- 'chia wallet show' now shows your wallet's height.
- Last Attempted Proof is now above Latest Block Challenge on the Farm page of the GUI.
- The GUI now detects duplicate plots and also only counts unique plots and unique plot size.
- We have integrated with crowdin to make it easier to translate the GUI. Check out [Chia Blockchain GUI](https://crowdin.com/project/chia-blockchain) there.
- We have added Italian, Russian, and Finnish. More to come soon.
- There is now remote UI support. [Documents](https://github.com/Chia-Network/chia-blockchain-gui/blob/main/remote.md) will temporarily live in the repository but have moved to the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki/Connecting-the-UI-to-a-remote-daemon). Thanks to @dkackman for this excellent addition!
- Added the ability to specify an address for the pool when making plots (-c flag), as opposed to a public key. The block
validation was changed to allow blocks like these to be made. This will enable changing pools in the future, by specifying a smart transaction for your pool rewards.
- Added `chia plots check --challenge-start [start]` that begins at a different `[start]` for `-n [challenges]`. Useful when you want to do more detailed checks on plots without restarting from lower challenge values you already have done. Huge thanks to @eFishCent for this and all of the debugging work behind the scenes confirming that plot failures were machine errors and not bugs!

### Changed

- Sub blocks renamed to blocks, and blocks renamed to transaction blocks, everywhere. This effects the RPC, now
all fields that referred to sub blocks are changed to blocks.
- Base difficulty and weight have increased, so difficulty of "5" in the rc1 testnet will be equivalent to "21990232555520" in the previous testnet.
- 'chia wallet send' now takes in TXCH or XCH as units instead of mojos.
- Transactions have been further sped up.
- The blockchain database has more careful validation.
- The GUI is now using bech32m.

### Fixed

- We updated chiapos to hopefully address some harvester crashes when moving plot files.
- Many of the cards on the Farming page have had bugs addressed including last block farmed, block rewards, and user fees.
- Improved validation of overflow blocks.


## [1.0beta27] aka Beta 1.27 - 2021-02-11

### Added

- The Beta 27 chain is a hard fork. All TXCH from previous releases has been reset on this chain. Your keys and plots of k=32 or larger continue to work just fine on this new chain.
- We now use the rust version of clvm, clvm_rs, in preference to validate transactions. We have additionally published binary wheels or clvm_rs for all four platforms and all three supported python versions. The rust version is approximately 50 times faster than the python version used to validate on chain transactions in previous versions.
- We have moved to compressed quadratic forms for VDFs. Using compressed representation of quadratic forms reduces their serialized size from 130 to 100 bytes (for forms with 1024-bit discriminant). This shrinks the size of VDF outputs and VDF proofs, and it's a breaking change as the compressed representation is not compatible with the older uncompressed (a, b) representation. Compressed forms are also used in calls to chiavdf and in timelord's communication with VDF clients. The form compression algorithm is based on ["Trustless Groups of Unknown Order with Hyperelliptic Curves"](https://eprint.iacr.org/2020/196) by Samuel Dobson, Steven D. Galbraith and Benjamin Smith.
- Last Attempted Proof on the Farm tab of the GUI now shows hours:minutes:seconds instead of just hours:minutes. This makes it much easier to see that your farmer is responding to recent challenges at a glance.
- You can now send and receive transactions with the command line. Try `chia wallet -h` to learn more. Also, `chia wallet` now requires a third argument of `show`, therefor you will use `chia wallet show` to see your wallet balance.
- We have added the [Crowdin](https://crowdin.com/) translation platform to [chia blockchain gui](https://crowdin.com/project/chia-blockchain). We are still getting it fully set up, but helping to translate the GUI is going to be much easier.
- Full Node > Connections in the GUI now shows the peak sub block height your connected peers believe they are at. A node syncing from you will not be at the true peak sub block height until it gets into sync.
- `chia init -c [directory]` will create new TLS certificates signed by your CA located in `[directory]`. Use this feature to configure a new remote harvester. Type `chia init -h` to get instructions. Huge thanks to a very efficient @eFishCent for this quick and thorough pull request.
- We build both MacOS x86_64 and MacOS universal wheels for chiapos, chiavdf, blpsy, and chiabip158 in Python 3.9. The universal build allows M1 Macs to run these dependencies in ARM64 native mode.
- On first run in the GUI (or when there are no plot directories) there is now an "Add Plot Directories" on the Farm tab also.

### Changed

- We are moving away from the terms sub blocks and blocks in our new consensus. What used to be called sub blocks will now just be blocks. Some blocks are now also transaction blocks. This is simpler both in the code and to reason about. Not all the code or UI may have caught up yet.
- This release has the final mainnet rewards schedule. During the first three years, each block winner will win 2 TXCH/XCH per block for a total of 9216 TXCH per day from 4608 challenges per day.
- Smart transactions now use an announcement instead of 'coin consumed' or lock methods.
- The GUI is now in a separate submodule repository from chia-blockchain, [chia-blockchain-gui](https://github.com/Chia-Network/chia-blockchain-gui). The installers and install scripts have been updated and it continues to follow the same install steps. Note that the GUI directory will now be `chia-blockchain-gui`. The workflow for this may be "touch and go" for people who use the git install methods over the short term.
- Very large coin counts are now supported.
- Various RPC endpoints have been renamed to follow our switch to "just blocks" from sub blocks.
- We've made changes to the protocol handshake and the blockchain genesis process to support mainnet launch and running/farming more than one chain at a time. That also means we can't as easily determine when an old version of the peer tries to connect so we will put warnings in the logs for now.
- We no longer replace addresses in the config. **IMPORTANT** - This means if you change the target address in config.yml, you have to make sure you control the correct keys.
- We now only migrate Beta 19 and newer installations.
- We have removed cbor2 as a dependency.
- We updated various dependencies including cryptography, packaging, portalocker, and pyyaml - most of which are only development dependencies.

### Fixed

- The function that estimated total farming space was counting space at twice the actual rate. Netspace will display half of the previous space estimate which is now a correct estimate of the actual space currently being farmed.
- We fixed many sync and stay in sync issue for both node and wallet including that both would send peaks to other peers multiple times and would validate the same transaction multiple times.
- The GUI was incorrectly reporting the time frame that the netspace estimate it displays utilizes. It is technically 312.5 minutes, on average, over the trailing 1000 sub blocks.
- Coloured coins were not working in the new consensus.
- Some Haswell processors do not have certain AVX extensions and therefor would not run.
- The cli wallet, `chia wallet`, was incorrectly displaying TXCH balances as if they were Coloured Coins.
- We addressed [CVE-2020-28477](https://nvd.nist.gov/vuln/detail/CVE-2020-28477) in the GUI.
- We made changes to CI to hopefully not repeat our skipped releases from the previous release cycle.

## [1.0beta26] aka Beta 1.26 - 2021-02-05

### Added

- We now use our own faster primality test based on Baillie-PSW. The new primality test is based on the 2020 paper ["Strengthening the Baillie-PSW primality test" by Robert Baillie, Andrew Fiori, Samuel S. Wagstaff Jr](https://arxiv.org/abs/2006.14425). The new test works approximately 20% faster than GMP library's mpz_probab_prime_p() function when generating random 1024-bit primes. This lowers the load on Timelords and speeds up VDF verifications in full node.
- The GUI now checks for an an already running GUI and stops the second launch. Thank you for that PR to @dkackman !
- Transactions are now validated in a separate process in full node.
- `chia plots check -l` will list all duplicate plot IDs found on the machine. Thanks very much for this PR @eFishCent.

### Changed

- Significant improvements have been made to how the full node handles the mempool. This generally cuts CPU usage of node by 2x or more. Part of this increase is that we have temporarily limited the size of transactions. If you want to test sending a transaction you should keep the value of your transaction below 20 TXCH as new consensus will cause you to use a lot of inputs. This will be returned to the expected level as soon as the integration of [clvm rust](https://github.com/Chia-Network/clvm_rs) is complete.
- We have changed the way TLS between nodes and between chia services work. Each node now has two certificate authorities. One is a public, shared CA that signs the TLS certificates that every node uses to connect to other nodes on 8444 or 58444. You now also have a self generated private CA that must sign e.g. farmer and harvester's certificates. To run a remote harvester you need a new harvester key that is then signed by your private CA. We know this is not easy for remote harvester in this release but will address it quickly.
- We have changed the way we compile the proof of space plotter and added one additional optimization. On many modern processors this will mean that using the plotter with the `-e` flag will be 2-3% faster than the Beta 17 plotter on the same CPU. We have found this to be very sensitive to different CPUs but are now confident that, at worst, the Beta 24 plotter with `-e` will be the same speed as Beta 17 if not slightly faster on the same hardware. Huge thanks to @xorinox for meticulously tracking down and testing this.
- If a peer is not responsive during sync, node will disconnect it.
- Peers that have not sent data in the last hour are now disconnected.
- We have made the "Help Translate" button in the GUI open in your default web browser and added instructions for adding new translations and more phrases in existing translations at that [URL](https://github.com/Chia-Network/chia-blockchain/tree/main/electron-react/src/locales). Try the "Help Translate" option on the language selection pull down to the left of the dark/light mode selection at the top right of the GUI.
- Sync store now tracks all connected peers and removes them as they get removed.
- The Rate Limited Wallet has been ported to new consensus and updated Chialisp methods.
- We are down to only one sub dependency that does not ship binary wheels for all four platforms. The only platform still impacted is ARM64 (generally Raspberry Pi) but that only means that you still need the minor build tools as outlined on the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki/Raspberry-Pi).
- We upgraded to Electron 9.4.2 for the GUI.
- We have upgraded to py-setproctitle 1.2.2. We now have binary wheels for setproctitle on all four platforms and make it a requirement in setup.py. It is run-time optional if you wish to disable it.

### Fixed

- On the Farm page of the GUI Latest Block Challenge is now populated. This shows you the actual challenge that came from the Timelord. Index is the signage point index in the current slot. There are 64 signage points every 10 minutes on average where 32 sub blocks can be won.
- Last Attempted Proof is now fixed. This will show you the last time one of your plots passed the [plot filter](https://github.com/Chia-Network/chia-blockchain/wiki/FAQ#what-is-the-plot-filter-and-why-didnt-my-plot-pass-it).
- Plot filename is now back in the Plots table of the GUI.
- There was a bug in adding a sub block to weight proofs and an issue in the weight proof index.
- Over time the node would think that there were no peers attached with peak sub block heights higher than 0.
- There was a potential bug in Python 3.9.0 that required us to update blspy, chiapos, chiavdf, and chiabip158.
- An off by one issue could cause syncing to ask for 1 sub block when it should ask for e.g. 32.
- Short sync and backtrack sync both had various issues.
- There was an edge case in bip158 handling.

### Known issues

- There is a remaining sync disconnect issue where your synced node will stop hearing responses from the network even though it still gets a few peaks and then stalls. Restarting node should let you quickly short sync back to the blockchain tip.

## [1.0beta25] aka Beta 1.25

### Skipped

## [1.0beta24] aka Beta 1.24

### Skipped

## [1.0beta23] aka Beta 1.23 - 2021-01-26

### Added

- The GUI now displays sub blocks as well as transaction blocks on the Full Node page.
- `chia plots check` enforces a minimum of `-n 5` to decrease false negatives. Thanks to @eFishCent for these ongoing pull requests!
- Testnets and mainnets will now have an initial period of sub blocks where transactions are blocked.
- Transaction volume testing added to tests and various tests have been sped up.
- We have added connection limits for max_inbound_wallet, max_inbound_farmer, and max_inbound_timelord.

### Changed

- On starting full node, the weight proof cache does not attempt to load all sub blocks. Startup times are noticeably improved though there remains a hesitation when validating the mempool. Our clvm Rust implementation, which will likely ship in the next release, will drop example processing times from 180 to 3 seconds.
- Changes to weight proofs and sub block storage and cacheing required a new database schema. This will require a re-sync or obtaining a synced blockchain_v23.db.
- clvm bytecode is now generated and confirmed that the checked-in clvm and ChiaLisp code matches the CI compiled code.
- We have removed the '-r' flag from `chia` as it was being overridden in most cases by the `-r` for restart flag to `chia start`. Use `chia --root-path` instead.
- `chia -h` now recommends `chia netspace -d 192` which is approximately one hours worth of sub blocks. Use `-d 1000` to get the same estimate of netspace as the RPC and GUI.
- `chia show -c` now displays in MiB and the GUI has been changed to MiB to match.
- `chia configure` now accepts the shorter `-upnp` and `-log-level` arguments also.
- `chia plots check` now defaults to `-n 30` instead of `-n 1` - HT @eFishCent.
- `chia plots create` now enforces a minimum of k=22. As a reminder, anything less than k=32 is just for testing and be careful extrapolating performance of a k less than 30 to a k=32 or larger.
- We have updated development dependencies for setuptools, yarl, idna, multidict, and chardet.
- Updated some copyright dates to 2021.

### Fixed

- We upgraded our fork of aiosqlite to version 16.0 which has significant performance improvements. Our fixes to aiosqlite are waiting to be upstreamed.
- The Plots tab in the GUI will no longer show red/error when the node is still syncing.
- Inbound and outbound peer connection limits were not being honored.
- Weight proofs were not correctly extending.
- In some cases when closing a p2p connection to another node, there was an infinite "Closing" loop.
- `chia show -c` was showing upload MiB in the download column and vice versa. @pyl and @psydafke deserves credit for insisting it was broken and @kd637xx for the PR assist.
- `chia show` handles sub block 0 better.

## [1.0beta22] aka Beta 1.22 - 2021-01-19

### Added

- Node now attempts to pre-validate and cache transactions.
- The harvester will try to not load a plot file that is too small for its k size. This should help keep from partial plots being found when they are copied into a harvester directory. Harvester will check again on the next challenge and find a completed copy of a plot file then.
- `chia plots create -x` skips adding [final dir] to harvester for farming

### Changed

- We now use bech32m and have added the bech32m tests from Pieter Wuille (@sipa) outlined [here](https://gist.github.com/sipa/14c248c288c3880a3b191f978a34508e) with thanks.
- In the GUI, choosing to parallel plot with a delay now is a delay between the start of the parallel plots started in one session.
- Removed loading plot file names when starting `chia plots create`; decreases plotter time when there are a lot of plots on the machine. Huge thanks to @eFishCent for this PR!

### Fixed

- Various fixes to improve node's ability to sync. There are still plenty of additional performance improvements coming for node so expect it to get easier to run on less powerful devices.
- Wallet now handles large amounts of coins much better and generally syncs better.
- Thanks to @nup002 for the PR to use scientific notation in the logs for address_manager.select_peer timings.
- `chia show -h` now correctly states that you use the first 8 characters of the node id to remove a node on the cli.
- Thank you to @wallentx for adding better help for `chia configure --enable-upnp`.
- Pull requests from forks won't have failures on CI.

## [1.0beta21] aka Beta 1.21 - 2021-01-16

### Added

- The cli now warns if you attempt to create a plot smaller than k=32.
- `chia configure` now lets you enable or disable uPnP.
- If a peer gives a bad weight proof it will now be disconnected.

### Changed

- Harvester now only checks every 2 minutes for new files and otherwise caches the plot listing in memory and logs how long it took to load all plot files at INFO level.
- Harvester multithreading is now configureable in config.yaml.
- Websocket heartbeat timeout was increased from 30 seconds to 300 seconds.
- Bumped Colorlog to 4.7.2, and pyinstaller to 4.2.

### Fixed

- Weight proofs were failing to verify contributing to a chain stall. This release gets things moving again but nodes are using too much CPU and can pause/lag at times. This may resolve as people upgrade to Beta 21.
- A toxic combination of transaction limits set too high and a non performant clvm kept the chain stalled. A faster rust implementation of clvm is already nearing completion.
- `chia netspace -s` would not correctly look up the start block height by block hash. Additionally netspace now flips to PiB above 1024 TiB. To compare netspace to `chia show` of the GUI use `chia netspace -d 1000` as `chia netspace` defaults to `-d 192` which is one hour.

## [1.0beta20] aka Beta 1.20 - 2021-01-14

### Added

- Plotting now checks to see if there are MacOS created `._` plot files and ignores them.
- Mnemonics now autocomplete in the GUI.

### Changed

- Node sync is now multithreaded and much quicker.
- Peer gossip is faster and smarter. It also will no longer accidentally gossip a private IP address to another peer.
- When syncing in the GUI, estimated time to win just shows syncing until synced.
- If harvester hits an exception it will be caught, logged and skipped. This normally happens if it attempts to harvest a plot file you are still copying in.
- The Rate Limited wallet has been updated to work in new consensus.

### Fixed

- There was a bug in block reorg code that would keep a peer with a lower weight chain from validating and syncing to a higher weight chain when the node thought it had a double spend in the other chain. This caused a persistent chain split.
- The Farm page in the GUI should not report just error when initially starting to sync.

## [1.0beta19] aka Beta 1.19 - 2021-01-12

### Added

- Welcome to the new consensus. This release is an all but a full re-write of the blockchain in under 30 days. There is now only one tip of the blockchain but we went from two chains to three. Block times are now a little under a minute but there are a couple of sub blocks between each transaction block. A block is also itself a special kind of sub block and each sub block rewards the farmer who won it 1 TXCH. Sub blocks come, on average, about every 17 to 18 seconds.
- Starting with this Beta, there are 4608 opportunities per day for a farmer to win 1 TXCH compared to Beta 18 where there were 288 opportunities per day for a farmer to win 16 TXCH.
- There is a lot more information and explanation of the new consensus algorithm in the New Consensus Working Document linked from [chia.net](https://chia.net/). Among the improvements this gives the Chia blockchain are a much higher security level against all attacks, more frequent transaction blocks that have less time variation between them and are then buried under confirmations (sub blocks also count towards re-org security) much more quickly.
- New consensus means this is a very hard fork. All of your TXCH from Beta 17/18 will be gone. Your plots and keys will work just fine however. You will have to sync to the new chain.
- You now have to sync 16 times more "blocks" for every 5 minutes of historical time so syncing is slower than it was on the old chain. We're aware of this and will be speeding it up and addressing blockchain database growth in the nest couple of releases.
- Prior to this Beta 19, we had block times that targeted 5 minutes and rewarded 16 TXCH to one farmer. Moving forward we have epoch times that target 10 minutes and reward 32 TXCH to 32 farmers about every 17-18 seconds over that period. This has subtle naming and UI impacts in various places.
- Total transaction throughput is still targeted at 2.1x Bitcoin's throughput per hour but you will get more confirmations on a transaction much faster. This release has the errata that it doesn't limit transaction block size correctly.
- For testing purposes this chain is quickly halving block rewards. By the time you're reading this and using the chain, farmers and pools will be receiving less than 1 TXCH for each block won as if it were 15-20 years from now. Block rewards are given in two components, 7/8's to the pool key and 1/8 to the farmer. The farmer also receives any transaction fees from the block.
- You can now plot in parallel using the GUI. A known limitation is that you can't yet specify that you want 4 sets of two parallel plots. Each parallel plot added starts immediately parallel. We will continue to improve this.
- The GUI now warns if you attempt to create a plot smaller than k=32.
- Added Chinese language localization (zh-cn). A big thank you to @goomario for their pull request!
- You can now specify which private key to use for `chia plots create`. After obtaining the fingerprint from `chia keys show`, try `chia plots create -a FINGERPRINT`. Thanks to @eFishCent for this pull request!
- We use a faster hash to prime function for chiavdf from the current release of gmp-6.2.1 which we have upgraded chiavdf and blspy to support.
- There is a new cli command - `chia configure`. This allows you to update certain configuration details like log level in config.yaml from the command line. This is particularly useful in containerization and linux automation. Try `chia configure -h`. Note that if chia services are running and you issue this command you will have to restart them for changes to take effect but you can use this command in the venv when no services are running or call it directly by path in the venv without activating the venv. Expect the options for this command to expand.
- We now fully support Python 3.9.

### Changed

- The Plot tab on the GUI is now the Plots tab. It starts out with a much more friendly new user wizard and otherwise keeps all of your farming plots listed here. Use the "+ ADD A PLOT" button in the top right to plot your second or later plot.
- The new plots page offers advanced plotting options in the various "Show Advanced Options" fold outs.
- The plotter supports the new bitfield back propagation method and the old method from Beta 17. To choose the old method add a `-e` to the command line or choose "Disable bitfield plotting" in "Show Advanced Options" of the Plots tab. Bitfield back propagation writes about 13% less total writes and can be faster on some slower hard drive temp spaces. For now, SSD temp space will likely plot faster with bitfield back propagation disabled. We will be returning to speed enhancements to the plotter as we approach and pass our mainnet launch.
- The Farm tab in the GUI is significantly enhanced. Here you have a dashboard overview of your farm and your activity in response to challenges blockchain challnegs, how long it will take you - on average - to win a block, and how much TXCH you've won so far. Harvester and Full Node connections have moved to Advanced Options.
- Harvester and farmer will start when the GUI starts instead of waiting for key selection if there are already keys available. This means you will start farming on reboot if you have the Chia application set to launch on start.
- Testnet is now running at the primary port of 58444. Update your routers appropriately. This opens 8444 for mainnet.
- All networking code has been refactored and mostly moved to websockets.
- RPCs and daemon now communicate over TLS with certificates that are generated into `~/.chia/VERSION/config/`
- We have moved to taproot across all of our transactions and smart transactions.
- We have adopted chech32m encoding of keys and addresses in parallel to bitcoin's coming adoption of bech32m.
- The rate limited wallet was updated and re-factored.
- All appropriate Chialisp smart transactions have been updated to use aggsig_me.
- Full node should be more aggressive about finding other peers.
- Peer disconnect messages are now set to log level INFO down from WARNING.
- chiavdf now allows passing in input to a VDF for new consensus.
- sha256tree has been removed from Chialisp.
- `chia show -s` has been refactored to support the new consensus.
- `chia netspace` has been refactored for new consensus.
- aiohttp, clvm-tools, colorlog, concurrent-log-handler, keyring, cryptography, and sortedcontainers have been upgraded to their current versions.
- Tests now place a cache of blocks and plots in the ~/.chia/ directory to speed up total testing time.
- Changes were made to chiapos to correctly support the new bitfiled backpropogation on FreeBSD and OpenBSD. With the exception of needing to work around python cryptography as outlined on the wiki, FreeBSD and OpenBSD should be able to compile and run chia-blockchain.
- With the change to new consensus many components of the chain and local database are not yet stored optimally. Startup and sync times may be slower than usual so please be patient. This will improve next release.
- Errata: Coinbase amount is missing from the GUI Block view.
- Eratta: wallet Backup, and Fly-sync on the wallet are currently not working.

### Fixed

- There was a regression in Beta 18 where the plotter took 499GiB of temp space for a k32 when it used to only use 332GiB. The plotter should now use just slightly less than it did in Beta 17.
- blspy was bumped to 0.3.1 which now correctly supports the aggsig of no signatures and is built with gmp-6.2.1.
- Fixed a plotter crash after pulling a disk without ejecting it first.
- `sh install.sh` now works properly on Linux Mint.
- `chia show -s` now is less brain dead when a node is initially starting to sync.

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
