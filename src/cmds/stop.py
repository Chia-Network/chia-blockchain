import asyncio

from .service_groups import all_groups, services_for_groups

from src.daemon.client import create_start_daemon_connection


def make_parser(parser):

    parser.add_argument(
        "group", choices=all_groups(), type=str, nargs="+",
    )
    parser.set_defaults(function=stop)


async def async_stop(args, parser):
    daemon = await create_start_daemon_connection(args.root_path)

    return_val = 0

    for service in services_for_groups(args.group):
        print(f"{service}: ", end="")
        if not await daemon.is_running(service_name=service):
            print("not running")
        elif await daemon.stop_service(service_name=service):
            print("stopped")
        else:
            print("stop failed")
            return_val = 1

    return return_val


def stop(args, parser):
    return asyncio.get_event_loop().run_until_complete(async_stop(args, parser))
