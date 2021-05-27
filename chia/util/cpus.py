import os
import multiprocessing


def get_available_cpus() -> int:
    try:
        cpu_count = os.sched_getaffinity(0)
    except AttributeError:
        cpu_count = multiprocessing.cpu_count()

    # Note: Windows Server 2016 has an issue https://bugs.python.org/issue26903
    if os.name == "nt":
        MAX = 61
        cpu_count = min(cpu_count, MAX)

    return cpu_count
