import asyncio
import signal
import subprocess
import sys


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


async def run_plotter(args, progress_dict):
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

    try:
        await asyncio.wait(
            [
                _read_stream(
                    process.stdout,
                    lambda x: parse_stdout(x.decode("UTF8"), progress_dict),
                ),
                _read_stream(
                    process.stderr,
                    lambda x: print("STDERR: {}".format(x.decode("UTF8"))),
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
