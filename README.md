# TadCoin Blockchain network

We're in the active development stage.

If you'd like to participate in testnet please [join our Discord](https://discord.gg/4dkydqsQ)

**How is this fork different?**

* We support both OG and NFT plots and get you **FULL** reward. Yes, that's right, full reward for any type of plots.
* Get most of the space on the hard drive - we support k28+ plots  
* Open Source and in forked off Chia Network. You can always audit code by diff'ing it with tad upstream
* You don't need goddamn nodes IP addresses. Tad's network is wholesome.

                                                         
### Ports used by TadCoin

➡ Full Node: **4044** ⬅

Other ports: 
- harvester: **4448**, RPC: **4458**
- farmer: **4447** , RPC: **4457**
- wallet: **4449**, RPC: **4456**
- timelord_launcher: **4050**
- timelord: **8446**
- node: **4044**, RPC: **8555**
- TAD daemon: **4400**

For unix system you can check if anything is using these ports with this handy command:
```
netstat -tnap | grep -e '4044|4448|4458|4447|4457|4050|8446|4044|8555'
```

---------------------------------

Below is a default tad readme:

![Alt text](https://www.tad.net/img/tad_logo.svg)

| Current Release/main | Development Branch/dev |
|         :---:          |          :---:         |
| [![Ubuntu Core Tests](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-ubuntu-core.yml/badge.svg)](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-ubuntu-core.yml) [![MacOS Core Tests](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-macos-core.yml/badge.svg)](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-macos-core.yml) [![Windows Installer on Windows 10 and Python 3.7](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-windows-installer.yml/badge.svg)](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-windows-installer.yml)  |  [![Ubuntu Core Tests](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-ubuntu-core.yml/badge.svg?branch=dev)](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-ubuntu-core.yml) [![MacOS Core Tests](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-macos-core.yml/badge.svg?branch=dev)](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-test-macos-core.yml) [![Windows Installer on Windows 10 and Python 3.7](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-windows-installer.yml/badge.svg?branch=dev)](https://github.com/Chia-Network/chia-blockchain/actions/workflows/build-windows-installer.yml) |

![GitHub contributors](https://img.shields.io/github/contributors/Chia-Network/chia-blockchain?logo=GitHub)

tad is a modern cryptocurrency built from scratch, designed to be efficient, decentralized, and secure. Here are some of the features and benefits:
* [Proof of space and time](https://docs.google.com/document/d/1tmRIb7lgi4QfKkNaxuKOBHRmwbVlGL4f7EsBDr_5xZE/edit) based consensus which allows anyone to farm with commodity hardware
* Very easy to use full node and farmer GUI and cli (thousands of nodes active on mainnet)
* Simplified UTXO based transaction model, with small on-chain state
* Lisp-style Turing-complete functional [programming language](https://chialisp.com/) for money related use cases
* BLS keys and aggregate signatures (only one signature per block)
* [Pooling protocol](https://www.tad.net/2020/11/10/pools-in-tad.html) (in development) that allows farmers to have control of making blocks
* Support for light clients with fast, objective syncing
* A growing community of farmers and developers around the world

Please check out the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki)
and [FAQ](https://github.com/Chia-Network/chia-blockchain/wiki/FAQ) for
information on this project.

Python 3.7+ is required. Make sure your default python version is >=3.7
by typing `python3`.

If you are behind a NAT, it can be difficult for peers outside your subnet to
reach you when they start up. You can enable
[UPnP](https://www.homenethowto.com/ports-and-nat/upnp-automatic-port-forward/)
on your router or add a NAT (for IPv4 but not IPv6) and firewall rules to allow
TCP port 4044 access to your peer.
These methods tend to be router make/model specific.

Most users should only install harvesters, farmers, plotter, full nodes, and wallets.
Building Timelords and VDFs is for sophisticated users, in most environments.
tad Network and additional volunteers are running sufficient Timelords
for consensus.

## Installing

Install instructions are available in the
[INSTALL](https://github.com/Chia-Network/chia-blockchain/wiki/INSTALL)
section of the
[chia-blockchain repository wiki](https://github.com/Chia-Network/chia-blockchain/wiki).

## Running

Once installed, a
[Quick Start Guide](https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide)
is available from the repository
[wiki](https://github.com/Chia-Network/chia-blockchain/wiki).
