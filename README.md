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
```

### Run servers
Run the servers in the following order (you can also use ipython):
```bash
python -m src.server.start_plotter
python -m src.server.start_timelord
python -m src.server.start_farmer
python -m src.server.start_full_node
```

### Run tests
```bash
py.test tests -s -v
```

### Run linting
```bash
flake8 src
pyright
```
