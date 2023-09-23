from __future__ import annotations

import time
from dataclasses import dataclass
from subprocess import check_call
from typing import Dict, List

import click
import psutil


@dataclass(frozen=True)
class Counters:
    user_time: int
    system_time: int


@click.command()
@click.argument("pid", type=int, required=True)
@click.option(
    "--output",
    type=str,
    default="cpu-usage.log",
    help="the file to print CPU usage stats to",
)
@click.option(
    "--threads",
    is_flag=True,
    default=False,
    help="Also capture threads counters",
)
def main(pid: int, output: str, threads: bool) -> None:
    process = psutil.Process(pid)

    stats: Dict[int, Dict[int, Counters]] = {pid: {}}
    timestamps: List[float] = []

    try:
        step = 0
        while process.is_running():
            timestamps.append(time.perf_counter())
            ps = process.cpu_times()
            stats[pid][step] = Counters(ps.user, ps.system)

            for p in process.children(recursive=True):
                try:
                    ps = p.cpu_times()
                    if p.pid not in stats:
                        stats[p.pid] = {}
                    stats[p.pid][step] = Counters(ps.user, ps.system)
                except Exception:
                    pass
            if threads:
                for t in process.threads():
                    try:
                        if t.id not in stats:
                            stats[t.id] = {}
                        stats[t.id][step] = Counters(t.user_time, t.system_time)
                    except Exception:
                        pass

            time.sleep(0.05)
            step += 1
    except psutil.NoSuchProcess:
        pass
    except KeyboardInterrupt:
        pass

    cols = sorted(stats.items())
    start_time = timestamps[0]
    with open(output, "w+") as out:
        out.write("timestamp ")
        for col_id, _ in cols:
            out.write(f"{col_id:5d}-user {col_id:6d}-sys ")
        out.write("\n")
        for row, ts in enumerate(timestamps):
            if row == 0:
                continue
            time_delta = ts - timestamps[row - 1]
            out.write(f"{ts-start_time:10f} ")
            for _, c in cols:
                if row in c and (row - 1) in c:
                    out.write(f"   {(c[row].user_time - c[row - 1].user_time)*100/time_delta:6.2f}% ")
                    out.write(f"   {(c[row].system_time - c[row - 1].system_time)*100/time_delta:6.2f}% ")
                else:
                    out.write("     0.00%      0.00% ")
            row += 1
            out.write("\n")

    with open("plot-cpu.gnuplot", "w+") as out:
        out.write(
            f"""
set term png small size 1500, {120*len(cols)}
set output "cpu.png"
set yrange [0:100]
unset xtics
set multiplot layout {len(cols)},1
"""
        )
        for idx, c2 in enumerate(cols):
            if c2[0] == pid:
                title = f"pid {c2[0]} (main)"
            else:
                title = f"pid {c2[0]}"

            out.write(f'set ylabel "CPU (%)\\n{title}"\n')
            if idx == len(cols) - 1:
                out.write('set xlabel "time (s)"\n')
            out.write(
                f'plot "{output}" using 1:(${idx*2+2}+${idx*2+3}) title "User" with filledcurves y=0, '
                f'"{output}" using 1:{idx*2+3} title "System" with filledcurves y=0\n'
            )

    print('running "gnuplot plot-cpu.gnuplot"')
    check_call(["gnuplot", "plot-cpu.gnuplot"])


if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    main()
