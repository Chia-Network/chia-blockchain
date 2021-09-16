import argparse
import binascii
import os
from pathlib import Path
from enum import Enum
from chia.plotters.chiapos import plot_chia
from chia.plotters.madmax import plot_madmax
from chia.plotters.bladebit import plot_bladebit


class Options(Enum):
    TMP_DIR = 1
    TMP_DIR2 = 2
    FINAL_DIR = 3
    FILENAME = 4
    K = 5
    MEMO = 6
    ID = 7
    BUFF = 8
    NUM_BUCKETS = 9
    STRIPE_SIZE = 10
    NUM_THREADS = 11
    NOBITFIELD = 12
    PLOT_COUNT = 13
    MADMAX_NUM_BUCKETS_PHRASE3 = 14
    MADMAX_WAITFORCOPY = 15
    POOLKEY = 16
    FARMERKEY = 17
    MADMAX_TMPTOGGLE = 18
    POOLCONTRACT = 19
    MADMAX_RMULTI2 = 20
    BLADEBIT_WARMSTART = 21
    BLADEBIT_NONUMA = 22
    VERBOSE = 23
    BLADEBIT_ID = 24
    BLADEBIT_OUTDIR = 25


chia_plotter = [
    Options.TMP_DIR,
    Options.TMP_DIR2,
    Options.FINAL_DIR,
    Options.FILENAME,
    Options.K,
    Options.MEMO,
    Options.ID,
    Options.BUFF,
    Options.NUM_BUCKETS,
    Options.STRIPE_SIZE,
    Options.NUM_THREADS,
    Options.NOBITFIELD,
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
]

bladebit_plotter = [
    Options.NUM_THREADS,
    Options.PLOT_COUNT,
    Options.FARMERKEY,
    Options.POOLKEY,
    Options.POOLCONTRACT,
    Options.BLADEBIT_WARMSTART,
    Options.BLADEBIT_ID,
    Options.BLADEBIT_NONUMA,
    Options.BLADEBIT_OUTDIR,
    Options.VERBOSE,
]


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
                "--tempdir",
                type=str,
                help="Temporary directory 1.",
                default=str(root_path) + "/",
            )
        if option is Options.TMP_DIR2:
            parser.add_argument(
                "-2",
                "--tempdir2",
                type=str,
                help="Temporary directory 2.",
                default=str(root_path) + "/",
            )
        if option is Options.FINAL_DIR:
            parser.add_argument(
                "-d",
                "--finaldir",
                type=str,
                help="Final directory.",
                default=str(root_path) + "/",
            )
        if option is Options.FILENAME:
            parser.add_argument(
                "-f",
                "--filename",
                type=str,
                help="Plot filename.",
                default="plot.dat",
            )
        if option is Options.BUFF:
            parser.add_argument(
                "-b",
                "--buffer",
                type=int,
                help="Size of the buffer, in MB.",
                default=0,
            )
        r_default = 0 if name == "chiapos" else 4
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
                type=bool,
                help="Disable bitfield.",
                default=False,
            )
        if option is Options.MEMO:
            parser.add_argument(
                "memo",
                type=binascii.unhexlify,
                help="Memo variable.",
            )
        if option is Options.ID:
            parser.add_argument(
                "id",
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
                type=bool,
                help="Wait for copy to start next plot",
                default=True,
            )
        if option is Options.MADMAX_TMPTOGGLE:
            parser.add_argument(
                "-G",
                "--tmptoggle",
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
                type=binascii.unhexlify,
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
                "farmerkey",
                type=binascii.unhexlify,
                help="Farmer Public Key (48 bytes)",
            )
        if option is Options.BLADEBIT_WARMSTART:
            parser.add_argument(
                "-w",
                "--warmstart",
                type=bool,
                help="Warm start (bool)",
                default=False,
            )
        if option is Options.BLADEBIT_NONUMA:
            parser.add_argument(
                "-m",
                "--nonuma",
                type=bool,
                help="Disable numa",
                default=False,
            )
        if option is Options.VERBOSE:
            parser.add_argument(
                "-v",
                "--verbose",
                type=bool,
                help="Set verbose",
                default=False,
            )
        if option is Options.BLADEBIT_ID:
            parser.add_argument(
                "-i",
                "--id",
                type=binascii.unhexlify,
                help="Plot id (used for debug)",
                default="",
            )
        if option is Options.BLADEBIT_OUTDIR:
            parser.add_argument(
                "-o",
                "--outdir",
                type=str,
                help="Output directory in which to output the plots. This directory must exist",
                default=str(root_path) + "/",
            )


def call_plotters(root_path, args):
    plotters = argparse.ArgumentParser(description="Available plotters.")
    subparsers = plotters.add_subparsers(help="Available plotters", dest="plotter")
    build_parser(subparsers, root_path, chia_plotter, "chiapos", "Chiapos Plotter")
    build_parser(subparsers, root_path, madmax_plotter, "madmax", "Madmax Plotter")
    build_parser(subparsers, root_path, bladebit_plotter, "bladebit", "Bladebit Plotter")

    args = plotters.parse_args(args)
    if args.plotter == "chiapos":
        plot_chia(args)
    if args.plotter == "madmax":
        plot_madmax(args, root_path)
    if args.plotter == "bladebit":
        plot_bladebit(args, root_path)
