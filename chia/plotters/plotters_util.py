from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, TextIO

from chia.util.chia_version import chia_short_version
from chia.util.config import lock_and_load_config


@contextlib.contextmanager
def get_optional_beta_plot_log_file(root_path: Path, plotter: str) -> Iterator[Optional[TextIO]]:
    beta_log_path: Optional[Path] = None
    with lock_and_load_config(root_path, "config.yaml") as config:
        if config.get("beta", {}).get("enabled", False):
            file_name = f"{plotter}_{datetime.now().strftime('%m_%d_%Y__%H_%M_%S')}.log"
            beta_log_path = Path(config["beta"]["path"]) / chia_short_version() / "plotting" / file_name
            beta_log_path.parent.mkdir(parents=True, exist_ok=True)
    if beta_log_path is not None:
        with open(beta_log_path, "w") as file:
            yield file
    else:
        yield None


# https://kevinmccarthy.org/2016/07/25/streaming-subprocess-stdin-and-stdout-with-asyncio-in-python/
async def _read_stream(stream, callback):
    while True:
        line = await stream.readline()
        if line:
            callback(line)
        else:
            break


def parse_stdout(out, progress):
    out = out.rstrip()
    print(out, flush=True)
    for k, v in progress.items():
        if k in out:
            print(f"Progress update: {v}", flush=True)


async def run_plotter(root_path, plotter, args, progress_dict):
    orig_sigint_handler = signal.getsignal(signal.SIGINT)
    installed_sigint_handler = False
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    def sigint_handler(signum, frame):
        process.terminate()

    # For Windows, we'll install a SIGINT handler to catch Ctrl-C (KeyboardInterrupt isn't raised)
    if sys.platform in ["win32", "cygwin"]:
        signal.signal(signal.SIGINT, sigint_handler)
        installed_sigint_handler = True

    with get_optional_beta_plot_log_file(root_path, plotter) as log_file:
        if log_file is not None:
            log_file.write(json.dumps(args) + "\n")

        def process_stdout_line(line_bytes: bytes) -> None:
            line_str = line_bytes.decode("UTF8")
            parse_stdout(line_str, progress_dict)
            if log_file is not None:
                log_file.write(line_str)

        def process_stderr_line(line_bytes: bytes) -> None:
            err_str = f"STDERR: {line_bytes.decode('UTF8')}"
            print(err_str)
            if log_file is not None:
                log_file.write(err_str)

        try:
            await asyncio.wait(
                [
                    asyncio.create_task(
                        _read_stream(
                            process.stdout,
                            process_stdout_line,
                        )
                    ),
                    asyncio.create_task(
                        _read_stream(
                            process.stderr,
                            process_stderr_line,
                        )
                    ),
                ]
            )

            await process.wait()
        except Exception as e:
            print(f"Caught exception while invoking plotter: {e}")
        finally:
            # Restore the original SIGINT handler
            if installed_sigint_handler:
                signal.signal(signal.SIGINT, orig_sigint_handler)


def run_command(args, exc_description, *, check=True, **kwargs) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(args, check=check, **kwargs)
    except Exception as e:
        raise RuntimeError(f"{exc_description} {e}")
    return proc


def reset_loop_policy_for_windows():
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def get_venv_bin():
    venv_dir = os.environ.get("VIRTUAL_ENV", None)
    if not venv_dir:
        return None

    venv_path = Path(venv_dir)

    if sys.platform == "win32":
        return venv_path / "Scripts"
    else:
        return venv_path / "bin"
