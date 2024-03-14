# Test CI Job generation

The CI jobs for these tests are managed by `build-job-matrix.py`.

The test matrix is generated with a command line like the following:
```
python3 tests/build-job-matrix.py --per directory --verbose > matrix.json
```

The command to build the matrix lives in [test.yml](https://github.com/Chia-Network/chia-blockchain/tree/main/.github/workflows/test.yml)

Tests are recognized by the file glob `test_*.py`.

We currently use github actions. Default runners have two vcpus.
The workflows are located in [../.github/workflows/](https://github.com/Chia-Network/chia-blockchain/tree/main/.github/workflows).

If the `--per directory` argument is used, each test subdirectory becomes a job in the github workflow matrix.

If your jobs run too long, simply move some tests into new subdirectories and re-push your branch.
A workflow built from a parent directory does not include the tests in its subdirectories.
The subdirectory jobs do not include the tests from their parents.
