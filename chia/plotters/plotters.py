import argparse
import binascii
import os
from enum import Enum
from chia.plotters.bladebit import get_bladebit_install_info, plot_bladebit
from chia.plotters.chiapos import get_chiapos_install_info, plot_chia
from chia.plotters.madmax import get_madmax_install_info, plot_madmax
from chia.plotters.install_plotter import install_plotter
from pathlib import Path
from typing import Any, Dict, Optional


class Options(Enum):
    TMP_DIR = 1
    TMP_DIR2 = 2
    FINAL_DIR = 3
    K = 4
    MEMO = 5
    ID = 6
    BUFF = 7
    NUM_BUCKETS = 8
    STRIPE_SIZE = 9
    NUM_THREADS = 10
    NOBITFIELD = 11
    PLOT_COUNT = 12
    MADMAX_NUM_BUCKETS_PHRASE3 = 13
    MADMAX_WAITFORCOPY = 14
    POOLKEY = 15
    FARMERKEY = 16
    MADMAX_TMPTOGGLE = 17
    POOLCONTRACT = 18
    MADMAX_RMULTI2 = 19
    BLADEBIT_WARMSTART = 20
    BLADEBIT_NONUMA = 21
    VERBOSE = 22
    OVERRIDE_K = 23
    ALT_FINGERPRINT = 24
    EXCLUDE_FINAL_DIR = 25
    CONNECT_TO_DAEMON = 26


chia_plotter = [
    Options.TMP_DIR,
    Options.TMP_DIR2,
    Options.FINAL_DIR,
    Options.K,
    Options.MEMO,
    Options.ID,
    Options.BUFF,
    Options.NUM_BUCKETS,
    Options.STRIPE_SIZE,
    Options.NUM_THREADS,
    Options.NOBITFIELD,
    Options.OVERRIDE_K,
    Options.ALT_FINGERPRINT,
    Options.POOLCONTRACT,
    Options.FARMERKEY,
    Options.POOLKEY,
    Options.PLOT_COUNT,
    Options.EXCLUDE_FINAL_DIR,
    Options.CONNECT_TO_DAEMON,
]

madmax_plotter = [
    Options.K,
    Options.PLOT_COUNT,
    Options.NUM_THREADS,
    Options.NUM_BUCKETS,
    Options.MADMAX_NUM_BUCKETS_PHRASE3,
    Options.TMP_DIR,
    Options.TMP_DIR2,
    Options.FINAL_DIR,
    Options.MADMAX_WAITFORCOPY,
    Options.POOLKEY,
    Options.FARMERKEY,
    Options.POOLCONTRACT,
    Options.MADMAX_TMPTOGGLE,
    Options.MADMAX_RMULTI2,
    Options.CONNECT_TO_DAEMON,
]

bladebit_plotter = [
    Options.NUM_THREADS,
    Options.PLOT_COUNT,
    Options.FARMERKEY,
    Options.POOLKEY,
    Options.POOLCONTRACT,
    Options.ID,
    Options.BLADEBIT_WARMSTART,
    Options.BLADEBIT_NONUMA,
    Options.FINAL_DIR,
    Options.VERBOSE,
    Options.CONNECT_TO_DAEMON,
]


def get_plotters_root_path(root_path: Path) -> Path:
    return root_path / "plotters"


def build_parser(subparsers, root_path, option_list, name, plotter_desc):
    parser = subparsers.add_parser(name, description=plotter_desc)
    for option in option_list:
        if option is Options.K:
            parser.add_argument(
                "-k",
                "--size",
                type=int,
                help="K value.",
                default=32,
            )
        u_default = 0 if name == "chiapos" else 256
        if option is Options.NUM_BUCKETS:
            parser.add_argument(
                "-u",
                "--buckets",
                type=int,
                help="Number of buckets.",
                default=u_default,
            )
        if option is Options.STRIPE_SIZE:
            parser.add_argument(
                "-s",
                "--stripes",
                type=int,
                help="Stripe size.",
                default=0,
            )
        if option is Options.TMP_DIR:
            parser.add_argument(
                "-t",
                "--tmp_dir",
                type=str,
                dest="tmpdir",
                help="Temporary directory 1.",
                default=str(root_path) + "/",
            )
        if option is Options.TMP_DIR2:
            parser.add_argument(
                "-2",
                "--tmp_dir2",
                type=str,
                dest="tmpdir2",
                help="Temporary directory 2.",
                default=str(root_path) + "/",
            )
        if option is Options.FINAL_DIR:
            parser.add_argument(
                "-d",
                "--final_dir",
                type=str,
                dest="finaldir",
                help="Final directory.",
                default=str(root_path) + "/",
            )
        if option is Options.BUFF:
            parser.add_argument(
                "-b",
                "--buffer",
                type=int,
                help="Size of the buffer, in MB.",
                default=0,
            )
        r_default = 4 if name == "madmax" else 0
        if option is Options.NUM_THREADS:
            parser.add_argument(
                "-r",
                "--threads",
                type=int,
                help="Num threads.",
                default=r_default,
            )
        if option is Options.NOBITFIELD:
            parser.add_argument(
                "-e",
                "--nobitfield",
                action="store_true",
                help="Disable bitfield.",
                default=False,
            )
        if option is Options.MEMO:
            parser.add_argument(
                "-m",
                "--memo",
                type=binascii.unhexlify,
                help="Memo variable.",
            )
        if option is Options.ID:
            parser.add_argument(
                "-i",
                "--id",
                type=binascii.unhexlify,
                help="Plot id",
            )
        if option is Options.PLOT_COUNT:
            parser.add_argument(
                "-n",
                "--count",
                type=int,
                help="Number of plots to create (default = 1)",
                default=1,
            )
        if option is Options.MADMAX_NUM_BUCKETS_PHRASE3:
            parser.add_argument(
                "-v",
                "--buckets3",
                type=int,
                help="Number of buckets for phase 3+4 (default = 256)",
                default=256,
            )
        if option is Options.MADMAX_WAITFORCOPY:
            parser.add_argument(
                "-w",
                "--waitforcopy",
                action="store_true",
                help="Wait for copy to start next plot",
                default=False,
            )
        if option is Options.MADMAX_TMPTOGGLE:
            parser.add_argument(
                "-G",
                "--tmptoggle",
                action="store_true",
                help="Alternate tmpdir/tmpdir2 (default = false)",
                default=False,
            )
        if option is Options.POOLCONTRACT:
            parser.add_argument(
                "-c",
                "--contract",
                type=str,
                help="Pool Contract Address (64 chars)",
                default="",
            )
        if option is Options.MADMAX_RMULTI2:
            parser.add_argument(
                "-K",
                "--rmulti2",
                type=int,
                help="Thread multiplier for P2 (default = 1)",
                default=1,
            )
        if option is Options.POOLKEY:
            parser.add_argument(
                "-p",
                "--pool-key",
                type=binascii.unhexlify,
                help="Pool Public Key (48 bytes)",
                default="",
            )
        if option is Options.FARMERKEY:
            parser.add_argument(
                "-f",
                "--farmerkey",
                type=binascii.unhexlify,
                help="Farmer Public Key (48 bytes)",
                default="",
            )
        if option is Options.BLADEBIT_WARMSTART:
            parser.add_argument(
                "-w",
                "--warmstart",
                action="store_true",
                help="Warm start",
                default=False,
            )
        if option is Options.BLADEBIT_NONUMA:
            parser.add_argument(
                "-m",
                "--nonuma",
                action="store_true",
                help="Disable numa",
                default=False,
            )
        if option is Options.VERBOSE:
            parser.add_argument(
                "-v",
                "--verbose",
                action="store_true",
                help="Set verbose",
                default=False,
            )
        if option is Options.OVERRIDE_K:
            parser.add_argument(
                "--override-k",
                dest="override",
                action="store_true",
                help="Force size smaller than 32",
                default=False,
            )
        if option is Options.ALT_FINGERPRINT:
            parser.add_argument(
                "-a",
                "--alt_fingerprint",
                type=int,
                default=None,
                help="Enter the alternative fingerprint of the key you want to use",
            )
        if option is Options.EXCLUDE_FINAL_DIR:
            parser.add_argument(
                "-x",
                "--exclude_final_dir",
                action="store_true",
                help="Skips adding [final dir] to harvester for farming",
                default=False,
            )
        if option is Options.CONNECT_TO_DAEMON:
            parser.add_argument(
                "-D",
                "--connect-to-daemon",
                action="store_true",
                help=argparse.SUPPRESS,
                default=False,
            )


def call_plotters(root_path: Path, args):
    # Add `plotters` section in CHIA_ROOT.
    chia_root_path = root_path
    root_path = get_plotters_root_path(root_path)
    if not root_path.is_dir():
        if os.path.exists(root_path):
            try:
                os.remove(root_path)
            except Exception as e:
                print(f"Exception deleting old root path: {type(e)} {e}.")

    if not os.path.exists(root_path):
        print(f"Creating plotters folder within CHIA_ROOT: {root_path}")
        try:
            os.mkdir(root_path)
        except Exception as e:
            print(f"Cannot create plotters root path {root_path} {type(e)} {e}.")
    plotters = argparse.ArgumentParser(description="Available options.")
    subparsers = plotters.add_subparsers(help="Available options", dest="plotter")
    build_parser(subparsers, root_path, chia_plotter, "chiapos", "Chiapos Plotter")
    build_parser(subparsers, root_path, madmax_plotter, "madmax", "Madmax Plotter")
    build_parser(subparsers, root_path, bladebit_plotter, "bladebit", "Bladebit Plotter")
    install_parser = subparsers.add_parser("install", description="Install custom plotters.")
    install_parser.add_argument(
        "install_plotter", type=str, help="The plotters available for installing. Choose from madmax or bladebit."
    )
    args = plotters.parse_args(args)

    if args.plotter == "chiapos":
        plot_chia(args, chia_root_path)
    if args.plotter == "madmax":
        plot_madmax(args, chia_root_path, root_path)
    if args.plotter == "bladebit":
        plot_bladebit(args, chia_root_path, root_path)
    if args.plotter == "install":
        install_plotter(args.install_plotter, root_path)


def get_available_plotters(root_path) -> Dict[str, Any]:
    plotters_root_path: Path = get_plotters_root_path(root_path)
    plotters: Dict[str, Any] = {}
    chiapos: Optional[Dict[str, Any]] = get_chiapos_install_info()
    bladebit: Optional[Dict[str, Any]] = get_bladebit_install_info(plotters_root_path)
    madmax: Optional[Dict[str, Any]] = get_madmax_install_info(plotters_root_path)

    if chiapos is not None:
        plotters["chiapos"] = chiapos
    if bladebit is not None:
        plotters["bladebit"] = bladebit
    if madmax is not None:
        plotters["madmax"] = madmax

    return plotters
