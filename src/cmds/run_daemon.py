import asyncio

from src.daemon.server import async_run_daemon


def make_parser(parser):
    parser.set_defaults(function=run_daemon)


def run_daemon(args, parser):
    return asyncio.get_event_loop().run_until_complete(async_run_daemon(args.root_path))
