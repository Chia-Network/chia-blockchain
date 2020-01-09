## Introduction
Welcome to the chia-blockchain project!
We are happy that you are taking a look at the code for Chia, a proof of space and time cryptocurrency.

A lot of fascinating new cryptography and blockchain concepts are used and implemented here.
This repo includes the code for the Chia full node, farmer, and timelord (in src), which are all written in python.
It also includes a verifiable delay function implementation under lib/chiavdf (in c/c++), and a proof of space implementation under lib/chiapos.

If you want to learn more about this project, read the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki), or check out the [green paper](https://www.chia.net/assets/ChiaGreenPaper.pdf).

### Contributions
We would be pleased to accept code contributions to this project.
As we are in the alpha stage, the main priority is getting a robust blockchain up and running, with as many of the mainnet features as possible.
If you are interested in cryptography, math, or just like hacking in python, there are many interesting problems to work on.
Contact any of the team members on keybase: https://keybase.io/team/chia_network.public, which we use as the main communication method.

### Run tests and linting
The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proofs of space during testing. The next time tests are run, this won't be necessary.

```bash
black src tests && flake8 src && mypy src tests
py.test tests -s -v
```
Black is used as an automatic style formatter to make things easier, and flake8 helps ensure consistent style.
Mypy is very useful for ensuring objects are of the correct type, so try to always add the type of the return value, and the type of local variables.

### Configure VS code
1. Install Python extension
2. Set the environment to ./.venv/bin/python
3. Install mypy plugin
4. Preferences > Settings > Python > Linting > flake8 enabled
5. Preferences > Settings > Python > Linting > mypy enabled
7. Preferences > Settings > Formatting > Python > Provider > black
6. Preferences > Settings > mypy > Targets: set to ./src and ./tests

### Submit changes
To submit changes, please make a pull request to the appropriate development branch.
For example, after the 1.2 release, the 1.3 branch is used for development, etc.
The master branch is updated with the latest releases only.
