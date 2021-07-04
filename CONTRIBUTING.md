# Introduction


If you want to learn more about this project we will update the wiki and green paper. While not available yet they will be found at: [wiki](https://github.com/Sector-Network/sector-blockchain/wiki), [green paper](https://www.sectornetwork.world/assets/SectorGreenPaper.pdf).

## Contributions

We would like to thank all the contributors of the Chia Network. Without them the Sector Network would not be around.

We ask that external contributors create a fork of the `main` branch for any feature work they wish to take on.

## Branching Strategy

1. All changes go into the main branch.
2. Main is stable at all times, all tests pass.
3. Features (with tests) are developed and fully tested on feature branches, and reviewed before landing in main.
4. Sector Network's nodes on the public testnet are running the latest version `x.y.z`.
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
black chia tests && mypy chia tests && flake8 chia tests
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
7. Preferences > Settings > mypy > Targets: set to `./chia` and `./tests`

## Configure Pycharm

Pycharm is an amazing and beautiful python IDE that some of us use to work on this project.
If you combine it with python black and formatting on save, you will get a very efficient
workflow.

1. pip install black
2. Run blackd in a terminal
3. Install BlackConnect plugin
4. Set to run python black on save
5. Set line length to 120
6. Install these linters https://github.com/Chia-Network/chia-blockchain/tree/main/.github/linters

## Testnets and review environments

With the launch of `1.0.0` we will begin running an official `testnet`.  
Prior to the release of `1.1.0` there will be two running test nets. `testnet` and `transaction-beta-testnet`. The `transaction-beta-testnet` testnet will be a beta of the pending 1.1 release, which will enable transactions on the chia blockchain.
Following the release of `1.1.0`, the official `testnet` will include all changes that have been accepted to the current release branch.

Prior to proposing changes to `main`, proposers should consider if running a `beta testnet` review environment will make the reviewer more effective when evaluating a change.
Changes that impact the blockchain could require a review environment before acceptance into `main`. This is at the discretion of the reviewer.
Chia organization members have been granted CI access to deploy `beta testnets`.
If you are not a Chia organization member, you can enquire about deploying a `beta testnet` in the public dev Keybase channel.

## Submit changes

To propose changes, please make a pull request to the `main` branch. See Branching Strategy above.

To propose changes for the production releases of Chia, please make a pull request to the latest release branch.

## Copyright

By contributing to this repository, you agree to license your work under the Apache License Version 2.0, or the MIT License, or release your work to the public domain. Any work contributed where you are not the original author must contain its license header with the original author(s) and be in the public domain, or licensed under the Apache License Version 2.0 or the MIT License.
