# chia-blockchain
Python 3.7 is used for this project.

### Install

```bash
# for Debian-based distros
sudo apt-get install build-essential cmake python3-dev --no-install-recommends

git submodule update --init --recursive
python3 -m venv .venv
. .venv/bin/activate
pip install wheel
pip install .
pip install lib/chiapos

cd lib/chiavdf/fast_vdf
# Install libgmp, libboost, and libflint, and then run the following
sh install.sh
```

### Run servers
When running the servers on Mac OS, allow the application to accept incoming connections.
Run the servers in the following order (you can also use ipython):
```bash
./lib/chiavdf/fast_vdf/vdf 8889
./lib/chiavdf/fast_vdf/vdf 8890
python -m src.server.start_plotter
python -m src.server.start_timelord
python -m src.server.start_farmer
python -m src.server.start_full_node "127.0.0.1" 8002 "-f" "-t"
python -m src.server.start_full_node "127.0.0.1" 8004
python -m src.server.start_full_node "127.0.0.1" 8005

```
Try running one of the full nodes after the other ones, to test initial sync.
Configuration of peers can be changed in src/config.
You can also run the simulation, which runs all servers at once.

```bash
./src/simulation/simulate_network.sh
```


### Run tests
The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proof of space during testing. The next time tests are run, this won't be necessary.
```bash
py.test tests -s -v
```

### Run linting
```bash
flake8 src
pyright
```
