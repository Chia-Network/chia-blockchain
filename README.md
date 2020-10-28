# chia-blockchain
![Alt text](https://www.chia.net/img/chia_logo.svg)

| Current Release/main | Development Branch/dev |
|         :---:          |          :---:         |
| ![Build Ubuntu on 3.7 and 3.8](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Ubuntu%20on%20Python%203.7%20and%203.8/badge.svg) ![Build MacOS](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20MacOS/badge.svg) ![Build Windows](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Windows/badge.svg)  |  ![Build Ubuntu on 3.7 and 3.8](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Ubuntu%20on%20Python%203.7%20and%203.8/badge.svg?branch=dev) ![Build MacOS](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20MacOS/badge.svg?branch=dev) ![Build Windows](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Windows/badge.svg?branch=dev) |

![GitHub contributors](https://img.shields.io/github/contributors/Chia-Network/chia-blockchain?logo=GitHub)

Please check out the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki)
and [FAQ](https://github.com/Chia-Network/chia-blockchain/wiki/FAQ) for
information on this project.

Python 3.7+ is required. Make sure your default python version is >=3.7
by typing `python3`.

If you are behind a NAT, it can be difficult for peers outside your subnet to
reach you when they start up. You can enable
[UPnP](https://www.homenethowto.com/ports-and-nat/upnp-automatic-port-forward/)
on your router or add a NAT (for IPv4 but not IPv6) and firewall rules to allow
TCP port 8444 access to your peer.
These methods tend to be router make/model specific.

Most should only install harvesters, farmers, plotter, full nodes, and wallets.
Building timelords and VDFs is for sophisticated users in most environments.
Chia Network and additional volunteers are running sufficient Timelords
for testnet consensus.

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
