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
        "chia plots create -k [size] -n [number of plots] -b [memory buffer size MiB] -r [number of threads] -u [number of buckets] -s [stripe size]"
        + " -f [farmer pk] -p [pool pk] -t [tmp dir] -2 [tmp dir 2] -d [final dir]  (creates plots)"
    )
    print("-i [plotid] [-m memo] are available for debugging")
    print("chia plots check -n [num checks]  (checks plots)")
    print("chia plots add -d [directory] (adds a directory of plots)")
    print("chia plots remove -d [directory] (removes a directory of plots from config)")
    print("chia plots show (shows the directory of current plots)")


def make_parser(parser):
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=26)
    parser.add_argument(
        "-n", "--num", help="Number of plots or challenges", type=int, default=None
    )
    parser.add_argument(
        "-b", "--buffer", help="Mebibytes for sort/plot buffer", type=int, default=0
    )
    parser.add_argument(
        "-r", "--num_threads", help="Number of threads to use", type=int, default=0
    )
    parser.add_argument(
        "-u", "--buckets", help="Number of buckets", type=int, default=0
    )
    parser.add_argument(
        "-s", "--stripe_size", help="Stripe size", type=int, default=0
    )
    parser.add_argument(
        "-f",
        "--farmer_public_key",
        help="Hex farmer public key",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-p", "--pool_public_key", help="Hex public key of pool", type=str, default=None
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
        raise RuntimeError(
            "Please initialize (or migrate) your config directory with chia init."
        )

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
