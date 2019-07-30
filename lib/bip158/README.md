## BIP158

This implements the compact block filter construction in BIP 158. The code is not used anywhere in the Bitcoin Core code base yet. The next step towards BIP 157 support would be to create an indexing module similar to TxIndex that constructs the basic and extended filters for each validated block.

### Install

```bash
git submodule update --init --recursive
python3 -m venv env
. env/bin/activate
pip3 install .
```

### Run python tests

Testings uses pytest.

```bash
python3 python-bindings/test.py
```


