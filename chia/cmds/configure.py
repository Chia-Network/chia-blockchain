from pathlib import Path
from typing import Dict

import click

from chia.util.config import load_config, save_config, str2bool
from chia.util.default_root import DEFAULT_ROOT_PATH


def configure(
    root_path: Path,
    set_farmer_peer: str,
    set_node_introducer: str,
    set_fullnode_port: str,
    set_log_level: str,
    enable_upnp: str,
):
    config: Dict = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    change_made = False
    if set_node_introducer:
        try:
            if set_node_introducer.index(":"):
                host, port = (
                    ":".join(set_node_introducer.split(":")[:-1]),
                    set_node_introducer.split(":")[-1],
                )
                config["full_node"]["introducer_peer"]["host"] = host
                config["full_node"]["introducer_peer"]["port"] = int(port)
                config["introducer"]["port"] = int(port)
                print("Node introducer updated")
                change_made = True
        except ValueError:
            print("Node introducer address must be in format [IP:Port]")
    if set_farmer_peer:
        try:
            if set_farmer_peer.index(":"):
                host, port = (
                    ":".join(set_farmer_peer.split(":")[:-1]),
                    set_farmer_peer.split(":")[-1],
                )
                config["full_node"]["farmer_peer"]["host"] = host
                config["full_node"]["farmer_peer"]["port"] = int(port)
                config["harvester"]["farmer_peer"]["host"] = host
                config["harvester"]["farmer_peer"]["port"] = int(port)
                print("Farmer peer updated, make sure your harvester has the proper cert installed")
                change_made = True
        except ValueError:
            print("Farmer address must be in format [IP:Port]")
    if set_fullnode_port:
        config["full_node"]["port"] = int(set_fullnode_port)
        config["full_node"]["introducer_peer"]["port"] = int(set_fullnode_port)
        config["farmer"]["full_node_peer"]["port"] = int(set_fullnode_port)
        config["timelord"]["full_node_peer"]["port"] = int(set_fullnode_port)
        config["wallet"]["full_node_peer"]["port"] = int(set_fullnode_port)
        config["wallet"]["introducer_peer"]["port"] = int(set_fullnode_port)
        config["introducer"]["port"] = int(set_fullnode_port)
        print("Default full node port updated")
        change_made = True
    if set_log_level:
        levels = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"]
        if set_log_level in levels:
            config["logging"]["log_level"] = set_log_level
            print(f"Logging level updated. Check {DEFAULT_ROOT_PATH}/log/debug.log")
            change_made = True
        else:
            print(f"Logging level not updated. Use one of: {levels}")
    if enable_upnp is not None:
        config["full_node"]["enable_upnp"] = str2bool(enable_upnp)
        if str2bool(enable_upnp):
            print("uPnP enabled")
        else:
            print("uPnP disabled")
        change_made = True
    if change_made:
        print("Restart any running chia services for changes to take effect")
        save_config(root_path, "config.yaml", config)
    return 0


@click.command("configure", short_help="Modify configuration")
@click.option("--set-node-introducer", help="Set the introducer for node - IP:Port", type=str)
@click.option("--set-farmer-peer", help="Set the farmer peer for harvester - IP:Port", type=str)
@click.option(
    "--set-fullnode-port",
    help="Set the port to use for the fullnode, useful for testing",
    type=str,
)
@click.option(
    "--set-log-level",
    "--log-level",
    "-log-level",
    help="Set the instance log level",
    type=click.Choice(["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"]),
)
@click.option(
    "--enable-upnp", "--upnp", "-upnp", help="Enable or disable uPnP", type=click.Choice(["true", "t", "false", "f"])
)
@click.pass_context
def configure_cmd(ctx, set_farmer_peer, set_node_introducer, set_fullnode_port, set_log_level, enable_upnp):
    configure(ctx.obj["root_path"], set_farmer_peer, set_node_introducer, set_fullnode_port, set_log_level, enable_upnp)
