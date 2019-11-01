# chia-blockchain
Python 3.7 is used for this project.

### Install

```bash
# for Debian-based distros
sudo apt-get install build-essential cmake python3-dev --no-install-recommends

git submodule update --init --recursive
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
pip install -r requirements.txt

cd lib/chiavdf/fast_vdf
# Install libgmp, libboost, and libflint, and then run the following
sh install.sh
```

### Run servers
When running the servers on Mac OS, allow the application to accept incoming connections.
Run the servers in the following order (you can also use ipython):
```bash
python -m src.server.start_plotter
python -m src.server.start_timelord
python -m src.server.start_farmer
python -m src.server.start_full_node "127.0.0.1" 8002 -f
python -m src.server.start_full_node "127.0.0.1" 8004 -t -u 8222
python -m src.server.start_full_node "127.0.0.1" 8005

```
Try running one of the full nodes a few minutes after the other ones, to test initial sync.
Configuration of peers can be changed in src/config.
You can also run the simulation, which runs all servers at once.

```bash
./src/simulation/simulate_network.sh
```

You can also ssh into the UI for the full node:
```bash
ssh -p 8222 localhost
```


### Run tests
The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proofs of space during testing. The next time tests are run, this won't be necessary.
```bash
py.test tests -s -v
```

### Run linting
```bash
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
