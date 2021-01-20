from src.util.config import (
    load_config,
    save_config,
)
from argparse import ArgumentParser
from typing import Dict
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.config import str2bool


def make_parser(parser: ArgumentParser):

    parser.add_argument(
        "--set-node-introducer",
        help="Set the introducer for node - IP:Port",
        type=str,
        nargs="?",
        default="",
    )

    parser.add_argument(
        "--set-fullnode-port",
        help="Set the port to use for the fullnode",
        type=str,
        nargs="?",
        default="",
    )

    parser.add_argument(
        "--set-log-level",
        "--log-level",
        "-log-level",
        help="Set the instance log level, Can be CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET",
        type=str,
        nargs="?",
        default="",
    )

    parser.add_argument(
        "--enable-upnp",
        "--upnp",
        "-upnp",
        help="Enable or disable uPnP. Can be True or False",
        type=str,
        nargs="?",
    )

    parser.set_defaults(function=configure)


def help_message():
    print("usage: chia configure -flag")
    print(
        """
        chia configure [arguments] [inputs]
            --set-node-introducer [IP:Port] (Set the introducer for node),
            --set-fullnode-port [Port] (Set the full node default port, useful for beta testing),
            --set-log-level [LogLevel] (Can be CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET),
            --enable-upnp,
            --upnp {True,False} (Enable or disable uPnP. Can be True or False)
        """
    )


def configure(args, parser):
    config: Dict = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    change_made = False
    if args.set_node_introducer:
        try:
            if args.set_node_introducer.index(":"):
                host, port = (
                    ":".join(args.set_node_introducer.split(":")[:-1]),
                    args.set_node_introducer.split(":")[-1],
                )
                config["full_node"]["introducer_peer"]["host"] = host
                config["full_node"]["introducer_peer"]["port"] = int(port)
                config["introducer"]["port"] = int(port)
                print("Node introducer updated.")
                change_made = True
        except ValueError:
            print("Node introducer address must be in format [IP:Port]")
    if args.set_fullnode_port:
        config["full_node"]["port"] = int(args.set_fullnode_port)
        config["full_node"]["introducer_peer"]["port"] = int(args.set_fullnode_port)
        config["farmer"]["full_node_peer"]["port"] = int(args.set_fullnode_port)
        config["timelord"]["full_node_peer"]["port"] = int(args.set_fullnode_port)
        config["wallet"]["full_node_peer"]["port"] = int(args.set_fullnode_port)
        config["wallet"]["introducer_peer"]["port"] = int(args.set_fullnode_port)
        config["introducer"]["port"] = int(args.set_fullnode_port)
        print("Default full node port updated.")
        change_made = True
    if args.set_log_level:
        if (
            (args.set_log_level == "CRITICAL")
            or (args.set_log_level == "ERROR")
            or (args.set_log_level == "WARNING")
            or (args.set_log_level == "INFO")
            or (args.set_log_level == "DEBUG")
            or (args.set_log_level == "NOTSET")
        ):
            config["logging"]["log_level"] = args.set_log_level
            print("Logging level updated. Check CHIA_ROOT/log/debug.log")
            change_made = True
    if args.enable_upnp is not None:
        config["full_node"]["enable_upnp"] = str2bool(args.enable_upnp)
        if str2bool(args.enable_upnp):
            print("uPnP enabled.")
        else:
            print("uPnP disabled.")
        change_made = True
    if change_made:
        print("Restart any running chia services for changes to take effect.")
        save_config(args.root_path, "config.yaml", config)
    else:
        help_message()
    return 0
