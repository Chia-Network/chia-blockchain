# chia-blockchain
Please check out the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki) and [FAQ](https://github.com/Chia-Network/chia-blockchain/wiki/FAQ) for information on this project.

Python 3.7 is required. Make sure your default python version is >=3.7 by typing `python3`.

You will need to enable [UPnP](https://www.homenethowto.com/ports-and-nat/upnp-automatic-port-forward/) on your router or add a NAT (for IPv4 but not IPv6) and firewall rules to allow TCP port 8444 access to your peer. These methods tend to be router make/model specific.

For alpha testnet most should only install harvesters, farmers, plotter and full nodes. Building timelords and VDFs is for sophisticated users in most environments. Chia Network and additional volunteers are running sufficient time lords for testnet consensus.

## Step 1: Install the code
To install the chia-blockchain node, follow [these](INSTALL.md) instructions according to your operating system.


## Step 2: Generate keys
First, create some keys by running the following script:
```bash
python -m scripts.regenerate_keys
```


## Step 3a: Run a full node
To run a full node on port 8444, and connect to the testnet, run the following command.
This will also start an ssh server in port 8222 for the UI, which you can connect to
to see the state of the node. If you want to see std::out log output, modify the logging.std_out
variable in ./config/config.yaml.

```bash
./scripts/run_full_node.sh
ssh -p 8222 localhost
```

## Step 3b: Run a farmer + full node
Instead of running only a full node (as in 4a), you can also run a farmer.
Farmers are entities in the network who use their hard drive space to try to create
blocks (like Bitcoin's miners), and earn block rewards. First, you must generate some hard drive plots, which
can take a long time depending on the [size of the plots](https://github.com/Chia-Network/chia-blockchain/wiki/k-sizes)
(the k variable). Then, run the farmer + full node with the following script. A full node is also started,
which you can ssh into to view the node UI (previous ssh command). You can also change the working directory and
final directory for plotting, with the "-t" and "-d" arguments to the create_plots script.
```bash
python -m scripts.create_plots -k 20 -n 10
sh ./scripts/run_farming.sh
```


## Step 3c: Run a timelord + full node
Timelords execute sequential verifiable delay functions (proofs of time), that get added to
blocks to make them valid. This requires fast CPUs and a lot of memory as well as completing
both install steps above.
```bash
sh ./scripts/run_timelord.sh
```

## Tips
When running the servers on Mac OS, allow the application to accept incoming connections.

Ubuntu 19.xx, Amazon Linux 2, and CentOS 7.7 or newer are the easiest linux install environments currently.

UPnP is enabled by default, to open port 8444 for incoming connections. If this causes issues,
you can disable it in the configuration. Some routers may require port forwarding, or enabling
UPnP in the router configuration.

Due to the nature of proof of space lookups by the harvester in the current alpha you should limit
the number of plots on a physical drive to 50 or less. This limit should significantly increase before beta.

You can also run the simulation, which runs all servers and multiple full nodes, locally, at once.

Note the the simulation is local only and requires installation of timelords and VDFs.

The introducer will only know the local ips of the full nodes, so it cannot broadcast the correct
ips to external peers.

```bash
sh ./scripts/run_all_simulation.sh
```

For increased networking performance, install uvloop:
```bash
pip install -e ".[uvloop]"
```

You can also use the [HTTP RPC](https://github.com/Chia-Network/chia-blockchain/wiki/Networking-and-Serialization#rpc) api to access information and control the full node:


```bash
curl -X POST  http://localhost:8555/get_blockchain_state
```

After installing, follow the remaining instructions in [README.md](README.md) to run the software.
