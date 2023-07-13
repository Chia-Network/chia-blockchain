from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import sys
import time
from types import FrameType
from typing import Any, Dict, Iterator, List

# This is a development utility that instruments tasks (coroutines) and records
# wall-clock time they spend in various functions. Since it relies on
# setprofile(), it cannot be combined with other profilers.

# to enable this instrumentation, set one of the environment variables:

#   CHIA_INSTRUMENT_NODE=1
#   CHIA_INSTRUMENT_WALLET=1

# Before starting the daemon.

# When exiting, profiles will be written to the `task-profile-<pid>` directory.
# To generate call trees, run:

# python chia/util/task_timing.py task-profile-<pid>


class FrameInfo:
    call_timestamp: float
    stack_pos: int

    def __init__(self) -> None:
        self.call_timestamp = 0.0
        self.stack_pos = 0


class CallInfo:
    duration: float
    calls: int

    def add(self, duration: float) -> None:
        self.duration += duration
        self.calls += 1

    def __init__(self, duration: float) -> None:
        self.duration = duration
        self.calls = 1


class TaskInfo:
    stack: Dict[FrameType, FrameInfo]
    stack_pos: int

    def __init__(self) -> None:
        self.stack = {}
        self.stack_pos = 0


g_next_id: int = 0


class FunctionInfo:
    name: str
    file: str
    num_calls: int
    duration: float
    callers: Dict[str, CallInfo]
    fun_id: int

    def __init__(self, name: str, file: str) -> None:
        global g_next_id

        self.name = name
        self.file = file
        self.num_calls = 0
        self.duration = 0.0
        self.callers = {}
        self.fun_id = g_next_id
        g_next_id += 1


# maps tasks to call-treea
g_function_infos: Dict[str, Dict[str, FunctionInfo]] = {}

g_tasks: Dict[asyncio.Task[Any], TaskInfo] = {}

g_cwd = os.getcwd() + "/"

# the frame object has the following members:
#   clear
#   f_back
#   f_builtins
#   f_code (type: "code")
#   f_globals
#   f_lasti
#   f_lineno
#   f_locals
#   f_trace
#   f_trace_lines
#   f_trace_opcodes

# the code class has the following members:
#   co_argcount
#   co_cellvars
#   co_code
#   co_consts
#   co_filename
#   co_firstlineno
#   co_flags
#   co_freevars
#   co_kwonlyargcount
#   co_lnotab
#   co_name
#   co_names
#   co_nlocals
#   co_posonlyargcount
#   co_stacksize
#   co_varnames
#   replace

# documented here: https://docs.python.org/3/library/inspect.html


def get_stack(frame: FrameType) -> str:
    ret = ""
    code = frame.f_code
    while code.co_flags & inspect.CO_COROUTINE:  # pylint: disable=no-member
        ret = f"/{code.co_name}{ret}"
        if frame.f_back is None:
            break
        frame = frame.f_back
        code = frame.f_code
    return ret


def strip_filename(name: str) -> str:
    if "/site-packages/" in name:
        return name.split("/site-packages/", 1)[1]
    if "/lib/" in name:
        return name.split("/lib/", 1)[1]
    if name.startswith(g_cwd):
        return name[len(g_cwd) :]
    return name


def get_fun(frame: FrameType) -> str:
    code = frame.f_code
    return f"{code.co_name}"


def get_file(frame: FrameType) -> str:
    code = frame.f_code
    return f"{strip_filename(code.co_filename)}:{code.co_firstlineno}"


def trace_fun(frame: FrameType, event: str, arg: Any) -> None:
    if sys.version_info < (3, 8):
        raise Exception(f"Python 3.8 or higher required, running with: {sys.version}")

    if event in ["c_call", "c_return", "c_exception"]:
        return

    # we only care about instrumenting co-routines
    if (frame.f_code.co_flags & inspect.CO_COROUTINE) == 0:  # pylint: disable=no-member
        # with open("instrumentation.log", "a") as f:
        #    f.write(f"[1]    {event} {get_fun(frame)}\n")
        return

    task = asyncio.current_task()
    if task is None:
        return

    global g_tasks
    global g_function_infos

    ti = g_tasks.get(task)
    if ti is None:
        ti = TaskInfo()
        g_tasks[task] = ti

    # t = f"{task.get_name()}"

    if event == "call":
        fi = ti.stack.get(frame)
        if fi is not None:
            ti.stack_pos = fi.stack_pos
            # with open("instrumentation.log", "a") as f:
            #    indent = " " * ti.stack_pos
            #    f.write(f"{indent}RESUME {t} {get_stack(frame)}\n")
        else:
            fi = FrameInfo()
            fi.stack_pos = ti.stack_pos
            fi.call_timestamp = time.perf_counter()
            ti.stack[frame] = fi
            ti.stack_pos += 1

    # indent = " " * ti.stack_pos
    # with open("instrumentation.log", "a") as f:
    #    f.write(f"{indent}CALL {t} {get_stack(frame)}\n")

    elif event == "return":
        fi = ti.stack.get(frame)
        assert fi is not None

        #        indent = " " * (fi.stack_pos)
        if asyncio.isfuture(arg):
            # this means the function was suspended
            # don't pop it from the stack
            pass
            # with open("instrumentation.log", "a") as f:
            #    f.write(f"{indent}SUSPEND {t} {get_stack(frame)}\n")
        else:
            # with open("instrumentation.log", "a") as f:
            #    f.write(f"{indent}RETURN {t} {get_stack(frame)}\n")

            now = time.perf_counter()
            duration = now - fi.call_timestamp

            task_name = task.get_name()
            fun_name = get_fun(frame)
            fun_file = get_file(frame)
            task_tree = g_function_infos.get(task_name)
            if task_tree is None:
                task_tree = {}
                g_function_infos[task_name] = task_tree
            fun_info = task_tree.get(fun_file)
            if fun_info is None:
                fun_info = FunctionInfo(fun_name, fun_file)
                task_tree[fun_file] = fun_info

            if frame.f_back is not None:
                n = get_file(frame.f_back)
                if n in fun_info.callers:
                    fun_info.callers[n].add(duration)
                else:
                    fun_info.callers[n] = CallInfo(duration)
            fun_info.num_calls += 1
            fun_info.duration += duration

            del ti.stack[frame]
        ti.stack_pos = fi.stack_pos - 1


def start_task_instrumentation() -> None:
    sys.setprofile(trace_fun)


def color(pct: float) -> str:
    assert pct >= 0 and pct <= 100
    return f"{int((100.-pct)//10)+1}"


def fontcolor(pct: float) -> str:
    if pct > 80 or pct < 20:
        return "white"
    else:
        return "black"


def stop_task_instrumentation(target_dir: str = f"task-profile-{os.getpid()}") -> None:
    sys.setprofile(None)
    global g_function_infos

    try:
        os.mkdir(target_dir)
    except Exception:
        pass
    for task, call_tree in g_function_infos.items():
        dot_file_name = f"{target_dir}/" + task + ".dot"
        total_duration = 0.0
        for name, fun_info in call_tree.items():
            total_duration = max(total_duration, fun_info.duration)

        if total_duration < 0.001:
            continue

        # ignore trivial call trees
        if len(call_tree) <= 2:
            continue

        filter_frames = set()

        with open(dot_file_name, "w") as f:
            f.write(
                "digraph {\n"
                'node [fontsize=11, colorscheme=rdylgn10, style=filled, fontname="Arial"]\n'
                'edge [fontsize=11, colorscheme=rdylgn10, fontname="Arial"]\n'
            )

            # print all nodes (functions)
            for name, fun_info in call_tree.items():
                # frames that are less than 0.1% of the total wall-clock time are
                # filtered
                if fun_info.duration / total_duration < 0.001:
                    filter_frames.add(name)
                    continue
                percent = fun_info.duration * 100 / total_duration
                f.write(
                    f'frame_{fun_info.fun_id} [shape=box, label="{fun_info.name}()\\l'
                    f"{fun_info.file}\\l"
                    f"{percent:0.2f}%\\n"
                    f"{fun_info.duration*1000:0.2f}ms\\n"
                    f'{fun_info.num_calls}x\\n",'
                    f"fillcolor={color(percent)}, "
                    f"color={color(percent)}, "
                    f"fontcolor={fontcolor(percent)}]\n"
                )

            # print all edges (calls)
            for name, fun_info in call_tree.items():
                if name in filter_frames:
                    continue

                for caller, ci in fun_info.callers.items():
                    caller_info = call_tree.get(caller)
                    if caller_info is None:
                        continue
                    if caller_info.file in filter_frames:
                        continue
                    percent = ci.duration * 100 / total_duration

                    # filter edges that are too insignificant
                    if percent < 0.01:
                        continue

                    f.write(
                        f"frame_{caller_info.fun_id} -> frame_{fun_info.fun_id} "
                        f'[label="{percent:0.2f}%\\n{ci.calls}x",'
                        f"penwidth={0.3+(ci.duration*6/total_duration):0.2f},"
                        f"color={color(percent)}]\n"
                    )
            f.write("}\n")


@contextlib.contextmanager
def manage_task_instrumentation() -> Iterator[None]:
    start_task_instrumentation()
    try:
        yield
    finally:
        stop_task_instrumentation()


@contextlib.contextmanager
def maybe_manage_task_instrumentation(enable: bool) -> Iterator[None]:
    if enable:
        with manage_task_instrumentation():
            yield
    else:
        yield


def main(args: List[str]) -> int:
    import glob
    import pathlib
    import subprocess

    profile_dir = pathlib.Path(args[0])
    queue: List[subprocess.Popen[bytes]] = []
    for file in glob.glob(str(profile_dir / "*.dot")):
        print(file)
        if os.path.exists(file + ".png"):
            continue

        if len(queue) > 15:
            oldest = queue.pop(0)
            oldest.wait()

        with open(file + ".png", "w+") as f:
            queue.append(subprocess.Popen(["dot", "-Tpng", file], stdout=f))

    while len(queue) > 0:
        oldest = queue.pop(0)
        oldest.wait()

    return 0


if __name__ == "__main__":
    sys.exit(main(args=sys.argv[1:]))
