from .start_stop import all_groups, services_for_groups, stop_service


def make_parser(parser):

    parser.add_argument(
        "group", choices=all_groups(), type=str, nargs="+",
    )
    parser.set_defaults(function=stop)


def stop(args, parser):
    return_val = 0

    for service in services_for_groups(args.group):
        if stop_service(args.root_path, service):
            return_val = 1

    return return_val
