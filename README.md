# chinilla-blockchain

![Alt text](https://www.chinilla.net/img/chinilla_logo.svg)

| Current Release/main | Development Branch/dev |
|         :---:          |          :---:         |
| [![Ubuntu Core Tests](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-ubuntu-core.yml/badge.svg)](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-ubuntu-core.yml) [![MacOS Core Tests](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-macos-core.yml/badge.svg)](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-macos-core.yml) [![Windows Installer on Windows 10 and Python 3.7](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-windows-installer.yml/badge.svg)](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-windows-installer.yml)  |  [![Ubuntu Core Tests](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-ubuntu-core.yml/badge.svg?branch=dev)](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-ubuntu-core.yml) [![MacOS Core Tests](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-macos-core.yml/badge.svg?branch=dev)](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-test-macos-core.yml) [![Windows Installer on Windows 10 and Python 3.7](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-windows-installer.yml/badge.svg?branch=dev)](https://github.com/Chinilla/chinilla-blockchain/actions/workflows/build-windows-installer.yml) |

![GitHub contributors](https://img.shields.io/github/contributors/Chinilla/chinilla-blockchain?logo=GitHub)

Chinilla is a modern cryptocurrency built from scratch, designed to be efficient, decentralized, and secure. Here are some of the features and benefits:
* [Proof of space and time](https://docs.google.com/document/d/1tmRIb7lgi4QfKkNaxuKOBHRmwbVlGL4f7EsBDr_5xZE/edit) based consensus which allows anyone to farm with commodity hardware
* Very easy to use full node and farmer GUI and cli (thousands of nodes active on vanillanet)
* [Chinilla seeder](https://github.com/Chinilla/chinilla-blockchain/wiki/Chinilla-Seeder-User-Guide), which maintains a list of reliable nodes within the Chinilla network via a built-in DNS server.
* Simplified UTXO based transaction model, with small on-chain state
* Lisp-style Turing-complete functional [programming language](https://chinillalisp.com/) for money related use cases
* BLS keys and aggregate signatures (only one signature per block)
* [Pooling protocol](https://github.com/Chinilla/chinilla-blockchain/wiki/Pooling-User-Guide) that allows farmers to have control of making blocks
* Support for light clients with fast, objective syncing
* A growing community of farmers and developers around the world

Please check out the [wiki](https://github.com/Chinilla/chinilla-blockchain/wiki)
and [FAQ](https://github.com/Chinilla/chinilla-blockchain/wiki/FAQ) for
information on this project.

Python 3.7+ is required. Make sure your default python version is >=3.7
by typing `python3`.

If you are behind a NAT, it can be difficult for peers outside your subnet to
reach you when they start up. You can enable
[UPnP](https://www.homenethowto.com/ports-and-nat/upnp-automatic-port-forward/)
on your router or add a NAT (for IPv4 but not IPv6) and firewall rules to allow
TCP port 42444 access to your peer.
These methods tend to be router make/model specific.

Most users should only install harvesters, farmers, plotter, full nodes, and wallets.
Setting up a seeder is best left to more advanced users.
Building Timelords and VDFs is for sophisticated users, in most environments.
Chinilla Network and additional volunteers are running sufficient Timelords
for consensus.

## Installing

Install instructions are available in the
[INSTALL](https://github.com/Chinilla/chinilla-blockchain/wiki/INSTALL)
section of the
[chinilla-blockchain repository wiki](https://github.com/Chinilla/chinilla-blockchain/wiki).

## Running

Once installed, a
[Quick Start Guide](https://github.com/Chinilla/chinilla-blockchain/wiki/Quick-Start-Guide)
is available from the repository
[wiki](https://github.com/Chinilla/chinilla-blockchain/wiki).
