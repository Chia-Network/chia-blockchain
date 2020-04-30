| Current Release/master | Development Branch/dev |
| :---: | :---: |
| ![Build Ubuntu and MacOS](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Ubuntu%20and%20MacOS/badge.svg) ![Build Windows Installer](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Windows%20Installer/badge.svg) |  ![Build Ubuntu and MacOS](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Ubuntu%20and%20MacOS/badge.svg?branch=dev) ![Build Windows Installer](https://github.com/Chia-Network/chia-blockchain/workflows/Build%20Windows%20Installer/badge.svg?branch=dev) |

# chia-blockchain
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

# Installing
Install instructions are available in the
[INSTALL](https://github.com/Chia-Network/chia-blockchain/wiki/INSTALL)
section of the
[chia-blockchain repository wiki](https://github.com/Chia-Network/chia-blockchain/wiki).

# Running
Once installed, a
[Quick Start Guide](https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide)
is available from the repository
[wiki](https://github.com/Chia-Network/chia-blockchain/wiki).

# Tips
Ubuntu 18.04 LTS, 19.xx, Amazon Linux 2, and CentOS 7.7 or newer are the
easiest linux install environments.

UPnP is enabled by default to open port 8444 for incoming connections.
If this causes issues, you can disable it in config.yaml.
Some routers may require port forwarding, or enabling UPnP
in the router's configuration.

Due to the nature of proof of space lookups by the harvester in the current
release you should limit the number of plots on a physical drive to 50 or less.
This limit will significantly increase soon.

# uvloop

For potentially increased networking performance on non Windows platforms,
install uvloop:
```bash
pip install -e ".[uvloop]"
```

# RPC Interface

You can also use the
[HTTP JSON-RPC](https://github.com/Chia-Network/chia-blockchain/wiki/Networking-and-Serialization#rpc)
api to access information and control the full node:

```bash
curl -X POST http://localhost:8555/get_blockchain_state
curl -d '{"header_hash":"afe223d75d40dd7bd19bf35846d0c9dce608bfc77ee5baa9f9cd6b98436e428b"}' -H "Content-Type: application/json" -X POST http://localhost:8555/get_header
```
