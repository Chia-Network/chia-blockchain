import argparse
import importlib

from src import __version__


SUBCOMMANDS = ["init", "show", "version"]


def create_parser():
    parser = argparse.ArgumentParser(
        description="Manage chia blockchain infrastructure (%s)." % __version__,
        epilog="You can combine -s and -c. Try 'watch -n 10 chia show -s -c' if you have 'watch' installed.",
    )

    subparsers = parser.add_subparsers()

    # this magic metaprogramming generalizes:
    #   from src.cmds import version
    #   new_parser = subparsers.add_parser(version)
    #   version.version_parser(new_parser)

    for subcommand in SUBCOMMANDS:
        mod = importlib.import_module("src.cmds.%s" % subcommand)
        mod.make_parser(subparsers.add_parser(subcommand))

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
