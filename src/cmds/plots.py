from pathlib import Path
import logging
from src.plotting.plot_tools import (
    add_plot_directory,
    remove_plot_directory,
    get_plot_directories,
)
from src.plotting.create_plots import create_plots
from src.plotting.check_plots import check_plots
from src.util.logging import initialize_logging


log = logging.getLogger(__name__)


command_list = ["create", "check", "add", "remove", "show"]


def help_message():
    print("usage: chia plots command")
    print(f"command can be any of {command_list}")
    print("")
    print(
        "chia plots create -k [size] -n [number of plots] -b [memory buffer size MiB]"
        + " -r [number of threads] -u [number of buckets] -s [stripe size]"
        + " -a [fingerprint] -f [farmer public key] -p [pool public key]"
        + " -t [tmp dir] -2 [tmp dir 2] -d [final dir] (creates plots)"
    )
    print("-e disables bitfield plotting")
    print("-x skips adding [final dir] to harvester for farming")
    print("-i [plotid] -m [memo] are available for debugging")
    print("chia plots check -n [challenges] -g [string] -l (checks plots)")
    print("  Default: check all plots in every directory with 30 challenges")
    print("  -n: number of challenges; 0 = skip opening plot files; can be used with -l")
    print("  -g: checks plots with file or directory name containing [string]")
    print("  -l: list plots with duplicate IDs")
    print("  Debugging options for chia plots check")
    print("    --debug-show-memo: shows memo to recreate the same exact plot")
    print("    --challenge-start [start]: begins at a different [start] for -n [challenges]")
    print("chia plots add -d [directory] (adds a directory of plots)")
    print("chia plots remove -d [directory] (removes a directory of plots from config)")
    print("chia plots show (shows the directory of current plots)")


def make_parser(parser):
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=32)
    parser.add_argument("-n", "--num", help="Number of plots or challenges", type=int, default=None)
    parser.add_argument("-b", "--buffer", help="Mebibytes for sort/plot buffer", type=int, default=4608)
    parser.add_argument("-r", "--num_threads", help="Number of threads to use", type=int, default=2)
    parser.add_argument("-u", "--buckets", help="Number of buckets", type=int, default=0)
    parser.add_argument("-s", "--stripe_size", help="Stripe size", type=int, default=0)
    parser.add_argument(
        "-a",
        "--alt_fingerprint",
        type=int,
        default=None,
        help="Enter the alternative fingerprint of the key you want to use",
    )
    parser.add_argument(
        "-c",
        "--pool_contract_address",
        type=str,
        default=None,
        help=(
            "Address of where the pool reward will be sent to. Only used "
            "if alt_fingerprint and pool public key are None"
        ),
    )
    parser.add_argument(
        "-f",
        "--farmer_public_key",
        help="Hex farmer public key",
        type=str,
        default=None,
    )
    parser.add_argument("-p", "--pool_public_key", help="Hex public key of pool", type=str, default=None)
    parser.add_argument(
        "-g",
        "--grep_string",
        help="Shows only plots that contain the string in the filename or directory name",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-t",
        "--tmp_dir",
        help="Temporary directory for plotting files",
        type=Path,
        default=Path("."),
    )
    parser.add_argument(
        "-2",
        "--tmp2_dir",
        help="Second temporary directory for plotting files",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "-d",
        "--final_dir",
        help="Final directory for plots (relative or absolute)",
        type=Path,
        default=Path("."),
    )
    parser.add_argument(
        "-i",
        "--plotid",
        help="PlotID in hex for reproducing plots (debugging only)",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-m",
        "--memo",
        help="Memo in hex for reproducing plots (debugging only)",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-e",
        "--nobitfield",
        help="Disable bitfield",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-x",
        "--exclude_final_dir",
        help="Skips adding [final dir] to harvester for farming",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-l",
        "--list_duplicates",
        help="List plots with duplicate IDs",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--debug-show-memo",
        help="Shows memo to recreate the same exact plot",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--challenge-start",
        help="Begins at a different [start] for -n [challenges]",
        type=int,
        default=None,
    )
    parser.add_argument(
        "command",
        help=f"Command can be any one of {command_list}",
        type=str,
        nargs="?",
    )

    parser.set_defaults(function=handler)
    parser.print_help = lambda self=parser: help_message()


def show(root_path):
    print("Directories where plots are being searched for:")
    print("Note that subdirectories must be added manually.")
    print(
        "Add with 'chia plots add -d [dir]' and remove with"
        + " 'chia plots remove -d [dir]'."
        + " Scan and check plots with 'chia plots check'"
    )
    print()
    for str_path in get_plot_directories(root_path):
        print(f"{str_path}")


def handler(args, parser):
    if args.command is None or len(args.command) < 1:
        help_message()
        parser.exit(1)

    root_path: Path = args.root_path
    if not root_path.is_dir():
        raise RuntimeError("Please initialize (or migrate) your config directory with chia init.")

    initialize_logging("", {"log_stdout": True}, root_path)
    command = args.command
    if command not in command_list:
        help_message()
        parser.exit(1)

    if command == "create":
        create_plots(args, root_path)
    elif command == "check":
        check_plots(args, root_path)
    elif command == "add":
        str_path = args.final_dir
        add_plot_directory(str_path, root_path)
    elif command == "remove":
        str_path = args.final_dir
        remove_plot_directory(str_path, root_path)
    elif command == "show":
        show(root_path)
