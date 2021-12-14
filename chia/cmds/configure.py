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
    set_harvester_port: str,
    set_log_level: str,
    enable_upnp: str,
    set_outbound_peer_count: str,
    set_peer_count: str,
    testnet: str,
    peer_connect_timeout: str,
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
    if set_harvester_port:
        config["harvester"]["port"] = int(set_harvester_port)
        config["farmer"]["harvester_peer"]["port"] = int(set_harvester_port)
        print("Default harvester port updated")
        change_made = True
    if set_log_level:
        levels = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"]
        if set_log_level in levels:
            config["logging"]["log_level"] = set_log_level
            print(f"Logging level updated. Check {DEFAULT_ROOT_PATH}/log/debug.log")
            change_made = True
        else:
            print(f"Logging level not updated. Use one of: {levels}")
    if enable_upnp:
        config["full_node"]["enable_upnp"] = str2bool(enable_upnp)
        if str2bool(enable_upnp):
            print("uPnP enabled")
        else:
            print("uPnP disabled")
        change_made = True
    if set_outbound_peer_count:
        config["full_node"]["target_outbound_peer_count"] = int(set_outbound_peer_count)
        print("Target outbound peer count updated")
        change_made = True
    if set_peer_count:
        config["full_node"]["target_peer_count"] = int(set_peer_count)
        print("Target peer count updated")
        change_made = True
    if testnet:
        if testnet == "true" or testnet == "t":
            print("Setting Testnet")
            testnet_port = "58444"
            testnet_introducer = "beta1_introducer.chia.net"
            testnet_dns_introducer = "dns-introducer-testnet7.chia.net"
            testnet = "testnet7"
            config["full_node"]["port"] = int(testnet_port)
            config["full_node"]["introducer_peer"]["port"] = int(testnet_port)
            config["farmer"]["full_node_peer"]["port"] = int(testnet_port)
            config["timelord"]["full_node_peer"]["port"] = int(testnet_port)
            config["wallet"]["full_node_peer"]["port"] = int(testnet_port)
            config["wallet"]["introducer_peer"]["port"] = int(testnet_port)
            config["introducer"]["port"] = int(testnet_port)
            config["full_node"]["introducer_peer"]["host"] = testnet_introducer
            config["full_node"]["dns_servers"] = [testnet_dns_introducer]
            config["selected_network"] = testnet
            config["harvester"]["selected_network"] = testnet
            config["pool"]["selected_network"] = testnet
            config["farmer"]["selected_network"] = testnet
            config["timelord"]["selected_network"] = testnet
            config["full_node"]["selected_network"] = testnet
            config["ui"]["selected_network"] = testnet
            config["introducer"]["selected_network"] = testnet
            config["wallet"]["selected_network"] = testnet
            print("Default full node port, introducer and network setting updated")
            change_made = True

        elif testnet == "false" or testnet == "f":
            print("Setting Mainnet")
            mainnet_port = "8444"
            mainnet_introducer = "introducer.chia.net"
            mainnet_dns_introducer = "dns-introducer.chia.net"
            net = "mainnet"
            config["full_node"]["port"] = int(mainnet_port)
            config["full_node"]["introducer_peer"]["port"] = int(mainnet_port)
            config["farmer"]["full_node_peer"]["port"] = int(mainnet_port)
            config["timelord"]["full_node_peer"]["port"] = int(mainnet_port)
            config["wallet"]["full_node_peer"]["port"] = int(mainnet_port)
            config["wallet"]["introducer_peer"]["port"] = int(mainnet_port)
            config["introducer"]["port"] = int(mainnet_port)
            config["full_node"]["introducer_peer"]["host"] = mainnet_introducer
            config["full_node"]["dns_servers"] = [mainnet_dns_introducer]
            config["selected_network"] = net
            config["harvester"]["selected_network"] = net
            config["pool"]["selected_network"] = net
            config["farmer"]["selected_network"] = net
            config["timelord"]["selected_network"] = net
            config["full_node"]["selected_network"] = net
            config["ui"]["selected_network"] = net
            config["introducer"]["selected_network"] = net
            config["wallet"]["selected_network"] = net
            print("Default full node port, introducer and network setting updated")
            change_made = True
        else:
            print("Please choose True or False")

    if peer_connect_timeout:
        config["full_node"]["peer_connect_timeout"] = int(peer_connect_timeout)
        change_made = True

    if change_made:
        print("Restart any running silicoin services for changes to take effect")
        save_config(root_path, "config.yaml", config)
    return 0


@click.command("configure", short_help="Modify configuration")
@click.option(
    "--testnet",
    "-t",
    help="configures for connection to testnet",
    type=click.Choice(["true", "t", "false", "f"]),
)
@click.option("--set-node-introducer", help="Set the introducer for node - IP:Port", type=str)
@click.option("--set-farmer-peer", help="Set the farmer peer for harvester - IP:Port", type=str)
@click.option(
    "--set-fullnode-port",
    help="Set the port to use for the fullnode, useful for testing",
    type=str,
)
@click.option(
    "--set-harvester-port",
    help="Set the port to use for the harvester, useful for testing",
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
    "--enable-upnp",
    "--upnp",
    "-upnp",
    help="Enable or disable uPnP",
    type=click.Choice(["true", "t", "false", "f"]),
)
@click.option(
    "--set_outbound-peer-count",
    help="Update the target outbound peer count (default 8)",
    type=str,
)
@click.option("--set-peer-count", help="Update the target peer count (default 80)", type=str)
@click.option("--set-peer-connect-timeout", help="Update the peer connect timeout (default 30)", type=str)
@click.pass_context
def configure_cmd(
    ctx,
    set_farmer_peer,
    set_node_introducer,
    set_fullnode_port,
    set_harvester_port,
    set_log_level,
    enable_upnp,
    set_outbound_peer_count,
    set_peer_count,
    testnet,
    set_peer_connect_timeout,
):
    configure(
        ctx.obj["root_path"],
        set_farmer_peer,
        set_node_introducer,
        set_fullnode_port,
        set_harvester_port,
        set_log_level,
        enable_upnp,
        set_outbound_peer_count,
        set_peer_count,
        testnet,
        set_peer_connect_timeout,
    )
