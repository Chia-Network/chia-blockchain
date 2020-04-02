# chia-blockchain
Please check out the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki) and [FAQ](https://github.com/Chia-Network/chia-blockchain/wiki/FAQ) for information on this project.

Python 3.7+ is required. Make sure your default python version is >=3.7 by typing `python3`.

If you are behind a NAT, it can be difficult for peers outside your subnet to reach you. You can enable
[UPnP](https://www.homenethowto.com/ports-and-nat/upnp-automatic-port-forward/) on your router or add a
NAT (for IPv4 but not IPv6) and firewall rules to allow TCP port 8444 access to your peer. These methods
tend to be router make/model specific.

For testnet most should only install harvesters, farmers, plotter and full nodes. Building timelords and VDFs is for sophisticated users in most environments. Chia Network and additional volunteers are running sufficient time lords for testnet consensus.

All data is now stored in the $CHIA_ROOT environment variable. or ~/.chia/VERSION-DIR/ if unset. You can find databases, keys, plots, logs here. You can set $CHIA_ROOT to the .chia directory in your home directory with `export CHIA_ROOT=~/.chia`.

## Step 1: Install the code
To install chia-blockchain, follow [these install](INSTALL.md) instructions according to your operating system. This only supports 64 bit operating systems.

Remember that once you complete your install you **must be in the Python virtual environment** which you access from the chia-blockchain directory with the command `. ./activate`. Both dots are critical and once executed correctly your cli prompt will look something like `(venv) username@machine:~$` with the (venv) prepended. Use `deactivate` should you want to exit the venv.

## Step 2: Generate keys
First, create some keys by running the following script:
```bash
chia-generate-keys
```

## Step 3a: Run a full node + wallet
To run a full node on port 8444, and connect to the testnet, run the following command.
If you want to see std::out log output, modify the logging.std_out variable in ./config/config.yaml.

```bash
chia-start-node &
chia-start-wallet-gui &
```

## Step 3b: Run a farmer + full node + wallet
Instead of running only a full node (as in 4a), you can also run a farmer.
Farmers are entities in the network who use their hard drive space to try to create
blocks (like Bitcoin's miners), and earn block rewards. First, you must generate some hard drive plots, which
can take a long time depending on the [size of the plots](https://github.com/Chia-Network/chia-blockchain/wiki/k-sizes)
(the k variable). Then, run the farmer + full node with the following script. A full node is also started.
You can also change the working directory and
final directory for plotting, with the "-t" and "-d" arguments to the create_plots script.
```bash
chia-create-plots -k 20 -n 10
chia-start-farmer &
chia-start-wallet-gui &
```


## Step 3c: Run a timelord + full node + wallet

*Note*
If you want to run a timelord on Linux, see LINUX_TIMELORD.md.

Timelords execute sequential verifiable delay functions (proofs of time or VDFs), that get added to
blocks to make them valid. This requires fast CPUs and a few cores per VDF as well as completing
both install steps above.
```bash
chia-start-timelord &
chia-start-wallet-gui &
```

## Tips
When running the servers on Mac OS, allow the application to accept incoming connections.

Ubuntu 18.04 LTS, 19.xx, Amazon Linux 2, and CentOS 7.7 or newer are the easiest linux install environments currently.

UPnP is enabled by default, to open port 8444 for incoming connections. If this causes issues,
you can disable it in the configuration. Some routers may require port forwarding, or enabling
UPnP in the router configuration.

Due to the nature of proof of space lookups by the harvester in the current release you should limit
the number of plots on a physical drive to 50 or less. This limit should significantly increase before soon.

You can also run the simulation, which runs all servers and multiple full nodes, locally, at once.

Note the the simulation is local only and requires installation of timelords and VDFs.

The introducer will only know the local ips of the full nodes, so it cannot broadcast the correct
ips to external peers.

```bash
chia-start-sim
```

## uvloop

For increased networking performance, install uvloop:
```bash
pip install -e ".[uvloop]"
```

You can also use the [HTTP RPC](https://github.com/Chia-Network/chia-blockchain/wiki/Networking-and-Serialization#rpc) api to access information and control the full node:


```bash
curl -X POST http://localhost:8555/get_blockchain_state
curl -d '{"header_hash":"afe223d75d40dd7bd19bf35846d0c9dce608bfc77ee5baa9f9cd6b98436e428b"}' -H "Content-Type: application/json" -X POST http://localhost:8555/get_header
```
