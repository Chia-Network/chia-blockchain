from src import __version__


def version(args, parser):
    print(__version__)


def make_parser(parser):
    parser.set_defaults(function=version)
    return parser
