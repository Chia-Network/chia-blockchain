from pathlib import Path
import logging
import pathlib
from src.plotting.plot_tools import add_plot_directory
from src.plotting.create_plots import create_plots
from src.plotting.check_plots import check_plots
from src.util.logging import initialize_logging
from argparse import ArgumentParser
from src.util.default_root import DEFAULT_ROOT_PATH


log = logging.getLogger(__name__)


command_list = [
    "create",
    "check",
    "add",
]


def help_message():
    print("usage: chia plots command")
    print(f"command can be any of {command_list}")
    print("")
    print(
        "chia plots create -k [size] -n [number of plots] -s [sk_seed] -i [index] -b [memory buffer size MB]"
        + " -f [farmer pk] -p [pool pk] -t [tmp dir] -2 [tmp dir 2] -d [final dir]  (creates plots)"
    )
    print("chia plots check -n [num checks]  (checks plots)")
    print("chia plots add -d [directory] (adds a directory of plots)")


def make_parser(parser):
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=26)
    parser.add_argument(
        "-n", "--num", help="Number of plots or challenges", type=int, default=None
    )
    parser.add_argument(
        "-i", "--index", help="First plot index", type=int, default=None
    )
    parser.add_argument(
        "-b", "--buffer", help="Megabytes for sort/plot buffer", type=int, default=2048
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
        "-s", "--sk_seed", help="Secret key seed in hex", type=str, default=None
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
        "command",
        help=f"Command can be any one of {command_list}",
        type=str,
        nargs="?",
    )

    parser.set_defaults(function=handler)
    parser.print_help = lambda self=parser: help_message()


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


def main():
    # TODO: remove: this is a hack to get pypacker to be able to call the script
    parser: ArgumentParser = ArgumentParser(description="Chia plots")
    parser.add_argument(
        "-r",
        "--root-path",
        help="Config file root (defaults to %s)." % DEFAULT_ROOT_PATH,
        type=pathlib.Path,
        default=DEFAULT_ROOT_PATH,
    )
    make_parser(parser)
    args = parser.parse_args()
    handler(args, parser)


if __name__ == "__main__":
    main()
