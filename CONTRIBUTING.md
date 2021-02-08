# Introduction

Welcome to the chia-blockchain project!
We are happy that you are taking a look at the code for Chia, a proof of space and time cryptocurrency.

A lot of fascinating new cryptography and blockchain concepts are used and implemented here.
This repo includes the code for the Chia GUI in electron/react and TypeScript.

It is an input to the [chia-blockchain](https://github.com/Chia-Network/chia-blockchain) repository which also includes a verifiable delay function implementation that it imports from the [chiavdf repo](https://github.com/Chia-Network/chiavdf) (in c/c++), and a proof of space implementation that it imports from the [chiapos repo](https://github.com/Chia-Network/chiapos). BLS signatures are imported from the [bls-signatures repo](https://github.com/Chia-Network/bls-signatures) as blspy. There is an additional dependency on the [chiabip158 repo](https://github.com/Chia-Network/chiabip158).
For major platforms, binary and source wheels are shipped to PyPI from each dependent repo and then chia-blockchain can pip install those from PyPI or they can be prepackaged as is done for the Windows and MacOS installer. On unsupported platforms, pip will fall back to the source distributions to be compiled locally.

If you want to learn more about this project, read the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki), or check out the [green paper](https://www.chia.net/assets/ChiaGreenPaper.pdf).

## Contributions

We would be pleased to accept code contributions to this project.
As we are in the alpha stage, the main priority is getting a robust blockchain up and running, with as many of the mainnet features as possible.
You can visit our [Trello project board](https://trello.com/b/ZuNx7sET) to get a sense of what is in the backlog.
Generally things to the left are in progress or done. Some things go through "Coming up soon" but some will come directly out of other columns.
Usually the things closer to the top of each column are the ones that will be worked on soonest.
If you are interested in cryptography, math, or just like hacking in python, there are many interesting problems to work on.
Contact any of the team members on [Keybase](https://keybase.io/team/chia_network.public), which we use as the main communication method and you can comment on any Trello card.

## Run tests and linting

The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proofs of space during testing. The next time tests are run, this won't be necessary.

```bash
. ./activate
pip install -r requirements-dev.txt
black src tests && mypy src tests && flake8 src tests
py.test tests -s -v --durations 0
```

Black is used as an automatic style formatter to make things easier, and flake8 helps ensure consistent style.
Mypy is very useful for ensuring objects are of the correct type, so try to always add the type of the return value, and the type of local variables.

If you want verbose logging for tests, edit the tests/pytest.ini file.

## Configure VS code

1. Install Python extension
2. Set the environment to ./venv/bin/python
3. Install mypy plugin
4. Preferences > Settings > Python > Linting > flake8 enabled
5. Preferences > Settings > Python > Linting > mypy enabled
6. Preferences > Settings > Formatting > Python > Provider > black
7. Preferences > Settings > mypy > Targets: set to ./src and ./tests

## Configure Pycharm

Pycharm is an amazing and beautiful python IDE that some of us use to work on this project.
If you combine it with python black and formatting on save, you will get a very efficient
workflow.

1. pip install black
2. Run blackd in a terminal
3. Install BlackConnect plugin
4. Set to run python black on save
5. Set line length to 120
6. Install mypy plugin

## Submit changes

To submit changes, please make a pull request to the `dev` development branch.

## Copyright

By contributing to this repository, you agree to license your work under the Apache License Version 2.0, or the MIT License, or release your work to the public domain. Any work contributed where you are not the original author must contain its license header with the original author(s) and be in the public domain, or licensed under the Apache License Version 2.0 or the MIT License.
