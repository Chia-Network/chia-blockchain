# Introduction

Welcome to the chia-blockchain project!
We are happy that you are taking a look at the code for Chia, a proof of space and time cryptocurrency.

A lot of fascinating new cryptography and blockchain concepts are used and implemented here.
This repo includes the code for the Chia full node, farmer, and timelord (in chia folder), which are all written in python.
It also includes a verifiable delay function implementation that it imports from the [chiavdf repo](https://github.com/Chia-Network/chiavdf) (in c/c++), and a proof of space implementation that it imports from the [chiapos repo](https://github.com/Chia-Network/chiapos). BLS signatures are imported from the [bls-signatures repo](https://github.com/Chia-Network/bls-signatures) as blspy. There is an additional dependency on the [chiabip158 repo](https://github.com/Chia-Network/chiabip158). For major platforms, binary and source wheels are shipped to PyPI from each dependent repo. Then chia-blockchain can pip install those from PyPI or they can be prepackaged as is done for the Windows installer. On unsupported platforms, pip will fall back to the source distributions, to be compiled locally.

If you want to learn more about this project, read the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki), or check out the [green paper](https://www.chia.net/assets/ChiaGreenPaper.pdf).

## Contributions

### Chia Flow Process Diagram
Please review this [diagram](https://drive.google.com/file/d/13LcNweYz8yoVTOY1n68PGXR7KJzbaDdq/view?usp=sharing), to better understand the git workflow.

### Getting Started
We would be pleased to accept code contributions to this project.
As we have now released, the main priority is improving the mainnet blockchain.
You can visit our [Trello project board](https://trello.com/b/ZuNx7sET) to get a sense of what is in the backlog.
Generally, things to the left are in progress or done. Some things go through "Coming up soon", but some will come directly out of other columns.
Usually, the things closer to the top of each column are the ones that will be worked on soonest.
If you are interested in cryptography, math, or just like hacking in python, there are many interesting problems to work on.
Contact any of the team members on [Keybase](https://keybase.io/team/chia_network.public), which we use as the main communication method. You can also comment on any Trello card.

We ask that external contributors create a fork of the `main` branch for any feature work they wish to take on.

Members of the Chia organization may create feature branches from the `main` branch.

In the event an emergency fix is required for the release version of Chia, members of the Chia organization will create a feature branch from the current release branch `1.0.0`.

### Chia Flow Branching Diagram

[Branching Strategy Diagram](https://drive.google.com/file/d/1mYmTi-aFgcyCc39pHyBaaBjV-vjvllBT/view?usp=sharing)

### Chia Flow Branching Strategy

1. All changes go into the `main` branch.
2. `main` is stable at all times, all tests pass pre merge.
3. Features (with tests) are developed and fully tested on feature branches, and reviewed before landing in main.
4. Chia Network's nodes on the public testnet are running the latest version of `main` updated every 12 hours.
5. The `main` branch will have a long running testnet to allow previewing of changes.
6. Pull request events may require a “beta testnet” review environment. At the moment this is at the discretion of the reviewer.
7. Hotfixes land in the candidate branch created for the emergency release. (cut a feature branch using the latest release tag and cut a new release from that branch to hotfix)
8. Releases requiring development under a change freeze will require the creation of short lived candidate branches which are merged back to `main` immediately prior to a release tag being cut.
9. A release tag (e.g. `1.1.1`) will be cut to initiate the release automation.
10. All Merge events will be squashed and merged

### Testnet and beta testnets

With the launch of `1.0.0`, we will begin running an official `testnet`.  This testnet is updated every 12 hours with code from `main`.

Prior to proposing changes to `main`, proposers should consider if running a `beta testnet` review environment will make the reviewer more effective when evaluating a change.
Changes that impact the blockchain could require a review environment, before acceptance into `main`. This is at the discretion of the reviewer.

Chia organization members have been granted CI access to deploy `beta testnets`.
If you are not a Chia organization member, you can enquire about deploying a `beta testnet` in the public Dev Keybase channel.

## Pre-Commit

We provide a [pre-commit configuration](https://github.com/Chia-Network/chia-blockchain/blob/main/.pre-commit-config.yaml) which triggers several useful
hooks (including linters/formatter) before each commit you make if you installed and set up [pre-commit](https://pre-commit.com/). This will help
to reduce the time you spend on failed CI jobs.

To install pre-commit on your system see https://pre-commit.com/#installation. After installation, you can either use it manually
with `pre-commit run` or let it trigger the hooks automatically before each commit by installing the
provided configuration with `pre-commit install`.

## How to:

### Make a release
If there is a candidate branch:
Resolve open PRs on the candidate branch and run testnet with the clients, from the most recent CI builds, to test the candidate version.
Create a commit to the candidate branch with the change log for the release.
Merge the candidate branch into main. (THIS HAS TO HAPPEN EVERY TIME)
Create a tag for this release number from the candidate branch (e.g., 1.0.1)
CI should cover everything but the announcements.
Delete the candidate branch
If there are no candidate branches:
Create a PR with the change log for the release.
Create a tag for this release number from main (e.g., 1.0.1.)    
CI should cover everything but the announcements.

### Make a candidate branch
Start with whichever merge commit hash that has the code we are comfortable releasing.
Git reset head to the hash for the merge commit of your choosing, or head if you simply want the current state of main as your fork point.
Git checkout -b candidate-x.x.x.
Git push (probably requires specifying of a remote branch,e.g., candidate-x.x.x)
Have engineers with changes for the release land their PRs on both main and the Candidate-x.x.x branch.
Candidates can be tested against the official testnet or against a beta testnet. The person managing the release will decide which pattern to use for testing.
Once the head of candidate-x.x.x is ready for release, submit a PR from the candidate branch back to main, wait till this PR is merged. Finally, create a tag from the candidate branch and delete the candidate branch when finished.

### Debug a specific configuration of main
To debug a past version of main when changes have been merged into main and after a bug you are working on was introduced:
Find the merge commit hash for the merge that introduced the bug producing changes.
Git checkout -b <testing_branch_name>.
Git reset --hard <commit hash>.
Git push.
Spin up a beta testnet for this branch.
Perform testing and patch the bug on your beta testnet.
Once ready with your patch, merge the head of main into your branch and submit a PR.

### Create an emergency patch
Should an emergency patch be required, the following should be performed:
Create a candidate branch (“candidate-xyx”) from the release tag we are patching.
git checkout <tag>
git checkout -b candidate-xyz
Patch this branch
Once patch is tested follow the same process of releasing from a candidate branch
It is imperative that this branch be merged to main and deleted after the release.

### Make a beta testnet (internal chia only)
Beta testnets can be generated from any non-main branch of the chia-blockchain repo.
If you would like to spin up a beta testnet, and you are an internal developer, ask in #devops
Run the workflow referenced from here https://github.com/Chia-Network/testnet-config-generator/actions/workflows/make-testnet.yml
This will create another branch and then trigger automation based on your source branch that also has constant changes for the testnet
Kick off the workflow and the rest is magic.
Candidate branches will have automatically deployed testnets via automation.

### Run tests and linting

The first time the tests are run, BlockTools will create and persist many plots. These are used for creating
proofs of space during testing. The next time tests are run, this will not be necessary.

```bash
. ./activate
pip install ".[dev]"
black chia tests && mypy chia tests && flake8 chia tests
py.test tests -v --durations 0
```

The [black library](https://black.readthedocs.io/en/stable/) is used as an automatic style formatter to make things easier.
The [flake8 library](https://readthedocs.org/projects/flake8/) helps ensure consistent style.
The [Mypy library](https://mypy.readthedocs.io/en/stable/) is very useful for ensuring objects are of the correct type, so try to always add the type of the return value, and the type of local variables.

If you want verbose logging for tests, edit the `tests/pytest.ini` file.

### Configure VS code

1. Install python extension
2. Set the environment to `./venv/bin/python`
3. Install mypy plugin
4. Preferences > Settings > Python > Linting > flake8 enabled
5. Preferences > Settings > Python > Linting > mypy enabled
6. Preferences > Settings > Formatting > Python > Provider > black
7. Preferences > Settings > mypy > Targets: set to `./chia` and `./tests`

### Configure Pycharm

Pycharm is an amazing and beautiful python IDE that some of us use to work on this project.
If you combine it with python black and formatting on save, you will get a very efficient
workflow.

1. pip install black
2. Run blackd in a terminal
3. Install BlackConnect plugin
4. Set to run python black on save
5. Set line length to 120
6. Install these linters https://github.com/Chia-Network/chia-blockchain/tree/main/.github/linters

### Submit changes

To propose changes, please make a pull request to the `main` branch. See Branching Strategy above.

## Copyright

By contributing to this repository, you agree to license your work under the Apache License Version 2.0, or the MIT License, or release your work to the public domain. Any work contributed where you are not the original author must contain its license header with the original author(s) and be in the public domain, or licensed under the Apache License Version 2.0 or the MIT License.
