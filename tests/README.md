# Test CI Job generation

The CI jobs for these tests are managed by `build-workflows.py`.

If you add a test file, or move one to another directory, please run `build-workflows.py`.
Tests are recognized by the file glob `test_*.py`.
Changing the contents of a file does not require running `build-workflows.py`.

We currently use github actions. Default runners have two vcpus.
The workflows are located in [../.github/workflows/](https://github.com/silicoin-network/silicoin-blockchain/tree/main/.github/workflows).

The inputs to `build-workflows.py` are the templates in `runner-templates`, the file `testconfig.py` in this directory, and the optional `config.py` files in some test subdirectories.
Files in the template directory ending in `include.yml` are included in jobs based on the per-directory settings.

The generated workflows are output to `../.github/workflows/`.

Each subdirectory below the directories `root_test_dirs` in `testconfig.py` becomes a job in the github workflow matrix.
If your jobs run too long, simply move some tests into new subdirectories and run `build-workflows.py`.
A workflow built from a parent directory does not include the tests in its subdirectories.
The subdirectory jobs do not include the tests from their parents.

## testconfig.py

In the top tests directory, [testconfig.py](https://github.com/silicoin-network/silicoin-blockchain/tree/main/tests/testconfig.py)
contains the application settings and the per-directory default settings.

## config.py

Each directory has an optional `config.py` file, which can override the per-directory default settings.

Per directory settings defaults:

```
parallel = False
checkout_blocks_and_plots = True
install_timelord = True
job_timeout = 30
```

### Parallel test execution

If you are certain that all the tests in a directory can run in parallel, set `parallel = True` in `config.py` inside that directory.

### Optional job stages

Set `checkout_blocks_and_plots` to `False` to omit checking out the [test-cache](https://github.com/Chia-Network/test-cache) repo.

Set `install_timelord` to `False` to omit the step of installing a Time Lord for your directory's job.

### Job Timeout

Set `job_timeout` to the number of minutes you want the CI system to wait before it kills your job.
Add two or three minutes to allow for job setup.
