from __future__ import annotations

import subprocess
import sys


def main() -> int:
    subprocess.run(
        [
            "poetry",
            "check",
            "--strict",
        ],
        check=True,
    )
    subprocess.run(
        [
            "poetry",
            "lock",
        ],
        check=True,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
