import asyncio
import cProfile
import logging
import pathlib

from chia.util.path import mkdir, path_from_root

# to use the profiler, enable it config file, "enable_profiler"
# the output will be printed to your chia root path, e.g. ~/.chia/mainnet/profile/
# to analyze the profile, run:

#   python chia/utils/profiler.py ~/.chia/mainnet/profile | less -r

# this will print CPU usage of the chia full node main thread at 1 second increments.
# find a time window of interest and analyze the profile file (which are in pstats format).

# for example:

#   python chia/utils/profiler.py ~/.chia/mainnet/profile 10 20


async def profile_task(root_path: pathlib.Path, log: logging.Logger) -> None:

    profile_dir = path_from_root(root_path, "profile")
    log.info("Starting profiler. saving to %s" % profile_dir)
    mkdir(profile_dir)

    counter = 0

    while True:
        pr = cProfile.Profile()
        pr.enable()
        # this will throw CancelledError when we're exiting
        await asyncio.sleep(1)
        pr.create_stats()
        pr.dump_stats(profile_dir / ("slot-%05d.profile" % counter))
        log.debug("saving profile %05d" % counter)
        counter += 1


if __name__ == "__main__":
    import sys
    import pstats
    import io
    from colorama import init, Fore, Back, Style
    from subprocess import check_call

    profile_dir = pathlib.Path(sys.argv[1])
    init(strip=False)

    def analyze_cpu_usage(profile_dir: pathlib.Path):
        counter = 0
        try:
            while True:
                f = io.StringIO()
                st = pstats.Stats(str(profile_dir / ("slot-%05d.profile" % counter)), stream=f)
                st.strip_dirs()
                st.sort_stats(pstats.SortKey.CUMULATIVE)
                st.print_stats()
                f.seek(0)
                total = 0.0
                sleep = 0.0

                # output looks like this:
                # ncalls  tottime  percall  cumtime  percall filename:lineno(function)
                # 1    0.000    0.000    0.000    0.000 <function>
                for line in f:

                    if " function calls " in line and " in " in line and " seconds":
                        # 304307 function calls (291692 primitive calls) in 1.031 seconds
                        assert total == 0
                        total = float(line.split()[-2])
                        continue
                    columns = line.split(None, 5)
                    if len(columns) < 6 or columns[0] == "ncalls":
                        continue

                    # TODO: to support windows and MacOS, extend this to a list of function known to sleep the process
                    # e.g. WaitForMultipleObjects or kqueue
                    if "{method 'poll' of 'select.epoll' objects}" in columns[5]:
                        # cumulative time
                        sleep += float(columns[3])

                if sleep < 0.000001:
                    percent = 100.0
                else:
                    percent = 100.0 * (total - sleep) / total

                if percent > 90:
                    color = Fore.RED + Style.BRIGHT
                elif percent > 80:
                    color = Fore.MAGENTA + Style.BRIGHT
                elif percent > 70:
                    color = Fore.YELLOW + Style.BRIGHT
                elif percent > 60:
                    color = Style.BRIGHT
                elif percent < 10:
                    color = Fore.GREEN
                else:
                    color = ""

                quantized = int(percent // 2)
                print(
                    ("%05d: " + color + "%3.0f%% CPU " + Back.WHITE + "%s" + Style.RESET_ALL + "%s|")
                    % (counter, percent, " " * quantized, " " * (50 - quantized))
                )

                counter += 1
        except Exception as e:
            print(e)

    def analyze_slot_range(profile_dir: pathlib.Path, first: int, last: int):
        if last < first:
            print("ERROR: first must be <= last when specifying slot range")
            return

        files = []
        for i in range(first, last + 1):
            files.append(str(profile_dir / ("slot-%05d.profile" % i)))

        output_file = "chia-hotspot-%d" % first
        if first < last:
            output_file += "-%d" % last

        print("generating call tree for slot(s) [%d, %d]" % (first, last))
        check_call(["gprof2dot", "-f", "pstats", "-o", output_file + ".dot"] + files)
        with open(output_file + ".png", "w+") as f:
            check_call(["dot", "-T", "png", output_file + ".dot"], stdout=f)
        print("output written to: %s.png" % output_file)

    if len(sys.argv) == 2:
        # this analyzes the CPU usage at all slots saved to the profiler directory
        analyze_cpu_usage(profile_dir)
    elif len(sys.argv) in [3, 4]:
        # the additional arguments are interpreted as either one slot, or a
        # slot range (first and last) to analyze
        first = int(sys.argv[2])
        last = int(sys.argv[3]) if len(sys.argv) == 4 else first
        analyze_slot_range(profile_dir, first, last)
    else:
        print(
            """USAGE:
profiler.py <profile-directory>
    Analyze CPU usage at each 1 second interval from the profiles in the specified
    directory. Print colored timeline to stdout
profiler.py <profile-directory> <slot>
profiler.py <profile-directory> <first-slot> <last-slot>
    Analyze a single slot, or a range of time slots, from the profile directory
"""
        )
