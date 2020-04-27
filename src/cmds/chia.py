import argparse
import importlib
import pathlib

from src import __version__
from src.util.default_root import DEFAULT_ROOT_PATH


SUBCOMMANDS = ["init", "generate", "show", "start", "stop", "version", "netspace"]


def create_parser():
    parser = argparse.ArgumentParser(
        description="Manage chia blockchain infrastructure (%s)." % __version__,
        epilog="Try 'chia start node', 'chat netspace -d 48', or 'chia show -s'.",
    )

    parser.add_argument(
        "-r",
        "--root-path",
        help="Config file root (defaults to %s)." % DEFAULT_ROOT_PATH,
        type=pathlib.Path,
        default=DEFAULT_ROOT_PATH,
    )

    subparsers = parser.add_subparsers()

    # this magic metaprogramming generalizes:
    #   from src.cmds import version
    #   new_parser = subparsers.add_parser(version)
    #   version.version_parser(new_parser)

    for subcommand in SUBCOMMANDS:
        mod = importlib.import_module("src.cmds.%s" % subcommand)
        mod.make_parser(subparsers.add_parser(subcommand))  # type: ignore

    parser.set_defaults(function=lambda args, parser: parser.print_help())
    return parser


def chia(args, parser):
    return args.function(args, parser)


def main():
    parser = create_parser()
    args = parser.parse_args()
    return chia(args, parser)


if __name__ == "__main__":
    main()
