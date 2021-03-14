# Building timelords

The Linux and MacOS chiavdf binary wheels currently exclude an executable
required to run a [Timelord](https://github.com/Chia-Network/chia-blockchain/wiki/Timelords).
If you want to run a Timelord on Linux or MacOS, you must install the wheel
from source (which may require some additional development packages) while in
the virtual environment.

```bash
. ./activate

sh install-timelord.sh
```

If the compile fails, it's likely due to a missing dependency.
[install-timelord.sh](https://github.com/Chia-Network/chia-blockchain/blob/main/install-timelord.sh)
attempts to install required build dependencies for Linux and MacOS before
invoking pip to build from the source python distribution of chiavdf.

The `install-timelord.sh` install script leverages two environmental variables
that the chiavdf wheels can use to specify how to build. `vdf_client` is the
service that the Timelord uses to run the VDF and prove the Proof of Time.
`vdf_bench` is a utility to get a sense of a given CPU's iterations per second.

- To build vdf_client set the environment variable BUILD_VDF_CLIENT to "Y".
`export BUILD_VDF_CLIENT=Y`.
- Similarly, to build vdf_bench set the environment variable BUILD_VDF_BENCH
to "Y". `export BUILD_VDF_BENCH=Y`.

Building and running Timelords in Windows x86-64 is not yet supported.
