# Introduction

Welcome to the hddcoin-blockchain project!
We are happy that you are taking a look at the code for HDDcoin, a proof of space and time cryptocurrency.

A lot of fascinating new cryptography and blockchain concepts are used and implemented here.
This repo includes the code for the HDDcoin full node, farmer, and timelord (in hddcoin folder), which are all written in python.
It also includes a verifiable delay function implementation that it imports from the [chiavdf repo](https://github.com/HDDcoin-Network/chiavdf) (in c/c++), and a proof of space implementation that it imports from the [chiapos repo](https://github.com/HDDcoin-Network/chiapos). BLS signatures are imported from the [bls-signatures repo](https://github.com/HDDcoin-Network/bls-signatures) as blspy. There is an additional dependency on the [chiabip158 repo](https://github.com/HDDcoin-Network/chiabip158). For major platforms, binary and source wheels are shipped to PyPI from each dependent repo. Then hddcoin-blockchain can pip install those from PyPI or they can be prepackaged as is done for the Windows installer. On unsupported platforms, pip will fall back to the source distributions, to be compiled locally.

If you want to learn more about this project, read the [wiki](https://github.com/HDDcoin-Network/hddcoin-blockchain/wiki), or check out the [green paper](https://www.hddcoin.org/assets/HDDcoinGreenPaper.pdf).

## Contributions

Please review this [diagram](https://drive.google.com/file/d/1r7AXTrj7gtD0Xy-9BtTZR6yv7WXMPgeM/view?usp=sharing), to better understand the git workflow.

We would be pleased to accept code contributions to this project.
As we have now released, the main priority is improving the mainnet blockchain.
You can visit our [Trello project board](https://trello.com/b/ZuNx7sET) to get a sense of what is in the backlog.
Generally, things to the left are in progress or done. Some things go through "Coming up soon", but some will come directly out of other columns.
Usually, the things closer to the top of each column are the ones that will be worked on soonest.
If you are interested in cryptography, math, or just like hacking in python, there are many interesting problems to work on.
Contact any of the team members on [Keybase](https://keybase.io/team/hddcoin_network.public), which we use as the main communication method. You can also comment on any Trello card.

We ask that external contributors create a fork of the `main` branch for any feature work they wish to take on.

Members of the HDDcoin organization may create feature branches from the `main` branch.

In the event an emergency fix is required for the release version of HDDcoin, members of the HDDcoin organization will create a feature branch from the current release branch `1.0.0`.

## Branching Strategy

[Branching Strategy Diagram](https://drive.google.com/file/d/1mYmTi-aFgcyCc39pHyBaaBjV-vjvllBT/view?usp=sharing)

1. All changes go into the main branch.
2. Main is stable at all times, all tests pass.
3. Features (with tests) are developed and fully tested on feature branches, and reviewed before landing in main.
4. HDDcoin Network's nodes on the public testnet are running the latest version `x.y.z`.
5. The `main` branch will have a long running `beta testnet` to allow previewing of changes.
6. Pull Request events may require a `beta testnet` review environment. At the moment this is at the discretion of the reviewer.
7. Hotfixes land in the release branch they fix, and all later versions. (This will be achieved by regularly merging from `1.0.x` to main).
8. Hotfixes that are emergency fixes for a specific version will be merged into (???), and removed from down-stream branches. This allows future merges without issues.
9. Whoever develops a hotfix is also responsible for merging it into all later branches.
10. A release branch (e.g. `1.1.x`) will be cut prior to a release, in order to separate work that should go into the release from work going into the next major release (main branch). (This pre-release branch will also have a `beta testnet` spun up for preview).
11. All Merge events will be squash merged.

## Run tests and linting

The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proofs of space during testing. The next time tests are run, this will not be necessary.

```bash
. ./activate
pip install ".[dev]"
black hddcoin tests && mypy hddcoin tests && flake8 hddcoin tests
py.test tests -v --durations 0
```

The [black library](https://black.readthedocs.io/en/stable/) is used as an automatic style formatter to make things easier.
The [flake8 library](https://readthedocs.org/projects/flake8/) helps ensure consistent style.
The [Mypy library](https://mypy.readthedocs.io/en/stable/) is very useful for ensuring objects are of the correct type, so try to always add the type of the return value, and the type of local variables.

If you want verbose logging for tests, edit the `tests/pytest.ini` file.

## Configure VS code

1. Install python extension
2. Set the environment to `./venv/bin/python`
3. Install mypy plugin
4. Preferences > Settings > Python > Linting > flake8 enabled
5. Preferences > Settings > Python > Linting > mypy enabled
6. Preferences > Settings > Formatting > Python > Provider > black
7. Preferences > Settings > mypy > Targets: set to `./hddcoin` and `./tests`

## Configure Pycharm

Pycharm is an amazing and beautiful python IDE that some of us use to work on this project.
If you combine it with python black and formatting on save, you will get a very efficient
workflow.

1. pip install black
2. Run blackd in a terminal
3. Install BlackConnect plugin
4. Set to run python black on save
5. Set line length to 120
6. Install these linters https://github.com/HDDcoin-Network/hddcoin-blockchain/tree/main/.github/linters

## Testnets and review environments

With the launch of `1.0.0` we will begin running an official `testnet`.  
Prior to the release of `1.1.0` there will be two running test nets. `testnet` and `transaction-beta-testnet`. The `transaction-beta-testnet` testnet will be a beta of the pending 1.1 release, which will enable transactions on the hddcoin blockchain.
Following the release of `1.1.0`, the official `testnet` will include all changes that have been accepted to the current release branch.

Prior to proposing changes to `main`, proposers should consider if running a `beta testnet` review environment will make the reviewer more effective when evaluating a change.
Changes that impact the blockchain could require a review environment before acceptance into `main`. This is at the discretion of the reviewer.
HDDcoin organization members have been granted CI access to deploy `beta testnets`.
If you are not a HDDcoin organization member, you can enquire about deploying a `beta testnet` in the public dev Keybase channel.

## Submit changes

To propose changes, please make a pull request to the `main` branch. See Branching Strategy above.

To propose changes for the production releases of HDDcoin, please make a pull request to the latest release branch.

## Copyright

By contributing to this repository, you agree to license your work under the Apache License Version 2.0, or the MIT License, or release your work to the public domain. Any work contributed where you are not the original author must contain its license header with the original author(s) and be in the public domain, or licensed under the Apache License Version 2.0 or the MIT License.
