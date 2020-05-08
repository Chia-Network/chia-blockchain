from src.daemon.server import run_daemon


def make_parser(parser):
    parser.set_defaults(function=daemon)


def daemon(args, parser):
    return run_daemon(args.root_path)
