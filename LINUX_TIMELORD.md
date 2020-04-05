The Linux chiavdf wheels are currently missing an executable required to run a timelord.
If you want to run a timelord on Linux, you must install the wheel from source (which may require some additional packages) while in the virtual environment.

```
. ./activate

pip install --force --no-binary chiavdf chiavdf==0.12.1
# or
sh install-timelord.sh
```

If the compile fails, it's likely due to a missing dependency. See [INSTALL.md](INSTALL.md) to determine
how to install dependent packages for your system.
