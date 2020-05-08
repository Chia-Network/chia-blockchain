import asyncio

from .service_groups import all_groups, services_for_groups

from src.daemon.client import create_start_daemon_connection


def make_parser(parser):
    parser.set_defaults(function=exit)


def exit(args, parser):
    return asyncio.get_event_loop().run_until_complete(async_exit(args, parser))


async def async_exit(args, parser):

    daemon = await create_start_daemon_connection(args.root_path)
    r = await daemon.exit(args.root_path)
    print(r)
