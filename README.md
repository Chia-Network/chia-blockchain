# chia-blockchain
Python 3.7 is used for this project.

### Install

```bash
git submodule update --init --recursive
python3 -m venv .venv
. .venv/bin/activate
pip install .
pip install lib/chiapos
```

### Run servers
Run the servers in the following order:
```bash
ipython src/server/start_plotter.py
ipython src/server/start_farmer.py
ipython src/server/start_full_node.py
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
