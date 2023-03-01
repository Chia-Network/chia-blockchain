from __future__ import annotations

import pathlib
import tracemalloc
from dataclasses import dataclass, field
from functools import lru_cache
from subprocess import check_call
from sys import stdout
from typing import Dict, List, Optional, Set

import click
from colorama import Back, Fore, Style, init


@dataclass
class CallInfo:
    size: int
    calls: int = 1

    def add(self, size: int) -> None:
        self.size += size
        self.calls += 1


@dataclass
class Frame:
    size: int
    fun_id: int
    count: int = 1
    callers: Dict[str, CallInfo] = field(default_factory=dict)

    def add(self, size: int) -> None:
        self.size += size
        self.count += 1


def color(pct: float) -> str:
    return f"{int((100.-pct)//10)+1}"


def fontcolor(pct: float) -> str:
    if pct > 80 or pct < 20:
        return "white"
    else:
        return "black"


@lru_cache(maxsize=10000)
def resolve_function(file: str, line: int) -> str:
    try:
        with open(file, "r") as f:
            all_lines: List[str] = []
            for row in f:
                all_lines.append(row)

        # line numbers start at 1
        while line > 0:
            line -= 1
            current = all_lines[line]
            if " def " in current or current.startswith("def "):
                return current.split("def ")[1].split("(")[0]
        return file.rsplit("/", 1)[1]
    except Exception:
        return "<unknown>"


@click.group(help="Analyze heap profile data created via `enable_memory_profiler` config options.")
@click.argument("profile_path", type=str)
@click.pass_context
def memory_profiler(ctx: click.Context, profile_path: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["profile_path"] = pathlib.Path(profile_path)


@memory_profiler.command(
    help="Analyze memory usage at 1 minute interval from the profiles in the specified directory. "
    "Print colored timeline to stdout"
)
@click.pass_context
def print_timeline(ctx: click.Context) -> None:
    init(strip=False)
    counter = 0
    try:
        while True:
            snapshot = tracemalloc.Snapshot.load(str(ctx.obj["profile_path"] / f"heap-{counter:05d}.profile"))
            # the total memory usage in MB
            total = sum(st.size for st in snapshot.statistics("filename")) / 1000000.0

            if total > 150:
                color = Fore.RED + Style.BRIGHT
            elif total > 120:
                color = Fore.MAGENTA + Style.BRIGHT
            elif total > 90:
                color = Fore.YELLOW + Style.BRIGHT
            elif total > 60:
                color = Style.BRIGHT
            elif total < 30:
                color = Fore.GREEN
            else:
                color = ""

            quantized = int(total // 20)
            print(f"{counter:05d}: {color}{total:3.0f} MB {Back.WHITE} {' ' * quantized}{Style.RESET_ALL}")

            counter += 1
    except Exception as e:
        print(e)


@memory_profiler.command(help="Analyze a single slot from the profile directory")
@click.argument("slot", type=int)
@click.pass_context
def analyze_slot(ctx: click.Context, slot: int) -> None:
    file = str(ctx.obj["profile_path"] / f"heap-{slot:05d}.profile")
    output_file = str(ctx.obj["profile_path"] / f"heap-{slot:05d}")

    print(f"generating call tree for slot {slot}")

    all_frames: Dict[str, Frame] = {}

    total_size = 0
    calls = 0
    snapshot = tracemalloc.Snapshot.load(file)
    for trace in snapshot.traces:
        prev_fun: Optional[str] = None
        total_size += trace.size
        calls += 1
        if ((calls - 1) & 255) == 0:
            stdout.write(f"\rtotal size: {total_size/1000000:0.3f} MB ({calls} allocs) ")
        # to support recursive functions, make sure we only visit each frame
        # once during traversal
        visited: Set[str] = set()
        for frame in trace.traceback:
            fun = resolve_function(frame.filename, frame.lineno)
            if fun in visited:
                prev_fun = fun
                continue

            visited.add(fun)

            if fun in all_frames:
                all_frames[fun].add(trace.size)
                if prev_fun:
                    if prev_fun in all_frames[fun].callers:
                        all_frames[fun].callers[prev_fun].add(trace.size)
                    else:
                        all_frames[fun].callers[prev_fun] = CallInfo(trace.size)
            else:
                all_frames[fun] = Frame(trace.size, len(all_frames))
                if prev_fun:
                    all_frames[fun].callers[prev_fun] = CallInfo(trace.size)
            prev_fun = fun

    print(f"\nwriting {output_file + '.dot'}")
    with open(output_file + ".dot", "w") as f:
        f.write(
            "digraph {\n"
            'node [fontsize=11, colorscheme=rdylgn10, style=filled, fontname="Arial"]\n'
            'edge [fontsize=11, colorscheme=rdylgn10, fontname="Arial"]\n'
        )

        filter_frames = set()

        for name, fr in all_frames.items():
            # frames that are less than 0.1% of the total allocations are
            # filtered
            if fr.size / total_size < 0.001:
                filter_frames.add(name)
                continue
            percent = fr.size * 100 / total_size
            f.write(
                f'frame_{fr.fun_id} [shape=box, label="{name}()\\l'
                f"{percent:0.2f}%\\n"
                f"{fr.size/1000000:0.3f}MB\\n"
                f'{fr.count}x\\n",'
                f"fillcolor={color(percent)}, "
                f"color={color(percent)}, "
                f"fontcolor={fontcolor(percent)}]\n"
            )

        # print all edges (calls)
        for name, fr in all_frames.items():
            if name in filter_frames:
                continue

            for caller, ci in fr.callers.items():
                caller_info = all_frames.get(caller)
                if caller_info is None:
                    continue
                if caller in filter_frames:
                    continue
                percent = ci.size * 100 / total_size

                # filter edges that are too insignificant
                if percent < 0.01:
                    continue

                caller_frame = all_frames.get(caller)
                assert caller_frame
                caller_id = caller_frame.fun_id
                f.write(
                    f"frame_{caller_id} -> frame_{fr.fun_id} "
                    f'[label="{percent:0.2f}%\\n{ci.calls}x",'
                    f"penwidth={0.3+(ci.size*6/total_size):0.2f},"
                    f"color={color(percent)}]\n"
                )
        f.write("}\n")
    print(f"writing {output_file}.png")
    with open(output_file + ".png", "wb") as f2:
        check_call(["dot", "-Tpng", output_file + ".dot"], stdout=f2)


if __name__ == "__main__":
    memory_profiler()  # pylint: disable = no-value-for-parameter
