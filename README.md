# chia-blockchain
Python 3.7 is used for this project. Make sure your python version is >=3.7 by typing python3.

### Install

```bash
# for Debian-based distros
sudo apt-get install build-essential cmake python3-dev python3-venv --no-install-recommends

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain
git submodule update --init --recursive
python3 -m venv .venv
. .venv/bin/activate
pip install wheel # For building blspy
pip install -e .
pip install -r requirements.txt

cd lib/chiavdf/fast_vdf
# Install libgmp, libboost, and libflint, and then run the following
sh install.sh
```

### Generate keys
First, create some keys by running the following script:
```bash
python -m src.scripts.regenerate_keys
```

### Run a full node
To run a full node on port 8002, and connect to the testnet, run the following command.
This wil also start an ssh server in port 8222 for the UI, which you can connect to
to see the state of the node.
```bash
python -m src.server.start_full_node "127.0.0.1" 8002 -u 8222 &
ssh -p 8222 localhost
```

### Run a farmer + full node
Farmers are entities in the network who use their hard drive space to try to create
blocks (like Bitcoin's miners), and earn block rewards. First, you must generate some hard drive plots, which
can take a long time depending on the size of the plots. Then, run the farmer + full node with
the following script. A full node is also started on port 8002, which you can ssh into to view the node UI.
```bash
python -m src.scripts.create_plots -k 20 -n 10
sh ./src/scripts/simulate_farming.sh
```

### Run a timelord + full node
Timelords execute sequential verifiable delay functions (proofs of time), that get added to
blocks to make them valid. This requires fast CPUs and a lot of memory.
```bash
sh ./src/scripts/simulate_farming.sh
```

### Tips
When running the servers on Mac OS, allow the application to accept incoming connections.
Try running one of the full nodes a few minutes after the other ones, to test initial sync.
Configuration of peers can be changed in src/config/config.yaml.
You can also run the simulation, which runs all servers and multiple full nodes, at once.

```bash
sh ./src/scripts/simulate_network.sh
```

### Run tests and linting
The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proofs of space during testing. The next time tests are run, this won't be necessary.
```bash
py.test tests -s -v
flake8 src
mypy src tests
```


### Configure VS code
1. Install Python extension
2. Set the environment to ./.venv/bin/python
3. Install mypy plugin
4. Preferences > Settings > Python > Linting > flake8 enabled
5. Preferences > Settings > Python > Linting > mypy enabled
6. Preferences > Settings > mypy > Targets: set to ./src and ./tests
