# chia-blockchain
Python 3.7 is used for this project. Make sure your default python version is >=3.7 by typing python3.

### Install on Debian/Ubuntu

```bash
sudo apt-get update
sudo apt-get install build-essential cmake python3-dev python3-venv --no-install-recommends mongodb-org=4.2.1
sh install.sh

# Run mongo database
mongod --fork --dbpath ./db/ --logpath mongod.log

. .venv/bin/activate
```
### Install on MacOS
Make sure [brew](https://brew.sh/) is available before starting the setup.
```bash
brew tap mongodb/brew
brew install cmake boost gmp mpir mpfr mongodb-community@4.2

git clone https://github.com/Chia-Network/chia-blockchain.git && cd chia-blockchain

git clone https://github.com/wbhart/flint2

sh install.sh

# Run mongo database
mongod --fork --dbpath ./db/ --logpath mongod.log

. .venv/bin/activate
```

### Generate keys
First, create some keys by running the following script:
```bash
python -m scripts.regenerate_keys
```

### Run a full node
To run a full node on port 8002, and connect to the testnet, run the following command.
This wil also start an ssh server in port 8222 for the UI, which you can connect to
to see the state of the node.
```bash
python -m src.server.start_full_node "127.0.0.1" 8444 -id 1 -u 8222 &
ssh -p 8222 localhost
```

### Run a farmer + full node
Farmers are entities in the network who use their hard drive space to try to create
blocks (like Bitcoin's miners), and earn block rewards. First, you must generate some hard drive plots, which
can take a long time depending on the size of the plots (the k variable). Then, run the farmer + full node with
the following script. A full node is also started, which you can ssh into to view the node UI (previous ssh command).
```bash
python -m scripts.create_plots -k 20 -n 10
sh ./scripts/run_farming.sh
```

### Run a timelord + full node
Timelords execute sequential verifiable delay functions (proofs of time), that get added to
blocks to make them valid. This requires fast CPUs and a lot of memory.
```bash
sh ./scripts/run_timelord.sh
```

### Tips
When running the servers on Mac OS, allow the application to accept incoming connections.

UPnP is enabled by default, to open the port for incoming connections. If this causes issues, you can disable it in the configuration. Some routers may require port forwarding, or enabling UPnP in the router configuration.

You can also run the simulation, which runs all servers and multiple full nodes, locally, at once.
If you want to run the simulation, change the introducer ip in ./config/config.yaml so that the full node points to the local introducer (127.0.0.1:8445).
Note the the simulation is local only.
The introducer will only know the local ips of the full nodes, so it cannot broadcast the correct ips to external peers.

```bash
sh ./scripts/run_all_simulation.sh
```

### Run tests and linting
The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proofs of space during testing. The next time tests are run, this won't be necessary.
Make sure to run mongo before running the tests.
```bash
mongod --dbpath ./db/ &
black src tests && flake8 src && mypy src tests
py.test tests -s -v
```


### Configure VS code
1. Install Python extension
2. Set the environment to ./.venv/bin/python
3. Install mypy plugin
4. Preferences > Settings > Python > Linting > flake8 enabled
5. Preferences > Settings > Python > Linting > mypy enabled
7. Preferences > Settings > Formatting > Python > Provider > black
6. Preferences > Settings > mypy > Targets: set to ./src and ./tests
