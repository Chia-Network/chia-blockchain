from __future__ import annotations

import asyncio
import logging
import pathlib
import tracemalloc
from datetime import datetime
from typing import Dict, List, Optional, Set

from chia.util.path import path_from_root


async def mem_profile_task(root_path: pathlib.Path, service: str, log: logging.Logger) -> None:

    profile_dir = path_from_root(root_path, f"memory-profile-{service}") / datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    log.info("Starting memory profiler. saving to %s" % profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        tracemalloc.start(30)

        counter = 0

        while True:
            # this will throw CancelledError when we're exiting
            await asyncio.sleep(60)
            snapshot = tracemalloc.take_snapshot()
            snapshot.dump(str(profile_dir / f"heap-{counter:05d}.profile"))
            log.info(f"Heap usage: {tracemalloc.get_traced_memory()[0]/1000000:0.3f} MB profile {counter:05d}")
            counter += 1
    finally:
        tracemalloc.stop()


if __name__ == "__main__":
    import sys
    from functools import lru_cache
    from subprocess import check_call
    from sys import stdout

    from colorama import Back, Fore, Style, init

    g_next_id: int = 0

    profile_dir = pathlib.Path(sys.argv[1])
    init(strip=False)

    def print_timeline() -> None:
        counter = 0
        try:
            while True:
                snapshot = tracemalloc.Snapshot.load(str(profile_dir / f"heap-{counter:05d}.profile"))
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

    def analyze_slot(slot: int) -> None:
        file = str(profile_dir / f"heap-{slot:05d}.profile")
        output_file = str(profile_dir / f"heap-{slot:05d}")

        print(f"generating call tree for slot {slot}")

        class CallInfo:
            size: int
            calls: int

            def add(self, size: int) -> None:
                self.size += size
                self.calls += 1

            def __init__(self, size: int) -> None:
                self.size = size
                self.calls = 1

        class Frame:
            count: int
            size: int
            callers: Dict[str, CallInfo]
            fun_id: int

            def __init__(self, size: int) -> None:
                global g_next_id
                self.count = 1
                self.size = size
                self.callers = {}
                self.fun_id = g_next_id
                g_next_id += 1

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
                    all_frames[fun].count += 1
                    all_frames[fun].size += trace.size
                    if prev_fun:
                        if prev_fun in all_frames[fun].callers:
                            all_frames[fun].callers[prev_fun].add(trace.size)
                        else:
                            all_frames[fun].callers[prev_fun] = CallInfo(trace.size)
                else:
                    all_frames[fun] = Frame(trace.size)
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

    if len(sys.argv) == 2:
        print_timeline()
    elif len(sys.argv) == 3:
        slot = int(sys.argv[2])
        analyze_slot(slot)
    else:
        print(
            """USAGE:
memory_profiler.py <profile-directory>
    Analyze memory usage at 1 minute interval from the profiles in the specified
    directory. Print colored timeline to stdout
memory_profiler.py <profile-directory> <slot>
    Analyze a single slot from the profile directory
"""
        )
