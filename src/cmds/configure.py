from src.util.config import load_config, save_config
from argparse import ArgumentParser
from typing import Dict
from src.util.default_root import DEFAULT_ROOT_PATH


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

    parser.set_defaults(function=configure)


def help_message():
    print("usage: chia configure -flag")
    print(
        """
        chia configure --set-node-introducer [IP:Port] (Set the introducer for node)
        chia configure --set-fullnode-port [Port] (Set the full node default port, useful for beta testing)
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
        print("Default full node port updated.")
        change_made = True
    if change_made:
        save_config(args.root_path, "config.yaml", config)
    else:
        help_message()
    return 0
