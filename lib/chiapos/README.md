# Chia Proof of Space

A prototype of Chia's proof of space, written in C++. Includes a plotter, prover, and verifier.
Only runs on 64 bit architectures with AES-NI support. Read the [Proof of Space document](https://www.chia.net/assets/proof_of_space.pdf) to learn about what proof of space is and how it works.

## C++ Usage Instructions

### Compile

```bash
mkdir -p build && cd build
cmake ../
cmake --build . -- -j 6
```

### Run tests

```bash
./RunTests
```

### CLI usage

```bash
./ProofOfSpace -k 25 -f "plot.dat" -m "0x1234" generate
./ProofOfSpace -f "plot.dat" prove <32 byte hex challenge>
./ProofOfSpace -k 25 verify <hex proof> <32 byte hex challenge>
./ProofOfSpace -f "plot.dat" check <iterations>
```

### Benchmark

```bash
time ./ProofOfSpace -k 25 generate
```


### Hellman Attacks usage

There is an experimental implementation which implements some of the Hellman Attacks that can provide significant space savings for the final file.


```bash
./HellmanAttacks -k 18 -f "plot.dat" -m "0x1234" generate
./HellmanAttacks -f "plot.dat" check <iterations>
```

## Python

Finally, python bindings are provided in the python-bindings directory.

### Install

```bash
git submodule update --init --recursive
python3 -m venv .venv
. .venv/bin/activate
pip3 install .
```

### Run python tests

Testings uses pytest. Type checking uses pyright, and linting uses flake8.

```bash
py.test ./tests -s -v
```
