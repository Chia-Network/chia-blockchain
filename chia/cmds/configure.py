from __future__ import annotations

import click

from chia.cmds.cmd_classes import ChiaCliContext
from chia.init.configure import configure


@click.command("configure", help="Modify configuration", no_args_is_help=True)
@click.option(
    "--testnet",
    "-t",
    help="configures for connection to testnet",
    type=click.Choice(["true", "t", "false", "f"]),
)
@click.option("--set-node-introducer", help="Set the introducer for node - IP:Port", type=str)
@click.option("--set-farmer-peer", help="Set the farmer peer for harvester - IP:Port", type=str)
@click.option("--set-solver-peer", help="Set the solver peer for farmer - IP:Port", type=str)
@click.option(
    "--set-solver-trusted-peers-only",
    help="Enable/disable trusted peer requirement for solver connections",
    type=click.Choice(["true", "t", "false", "f"]),
)
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
    "--log-systemd",
    help="Enable or disable systemd logging",
    type=click.Choice(["true", "t", "false", "f"]),
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
@click.option(
    "--crawler-db-path",
    help="configures the path to the crawler database",
    type=str,
)
@click.option(
    "--crawler-minimum-version-count",
    help="configures how many of a particular version must be seen to be reported in logs",
    type=int,
)
@click.option(
    "--seeder-domain-name",
    help="configures the seeder domain_name setting. Ex: `seeder.example.com.`",
    type=str,
)
@click.option(
    "--seeder-nameserver",
    help="configures the seeder nameserver setting. Ex: `example.com.`",
    type=str,
)
@click.pass_context
def configure_cmd(
    ctx: click.Context,
    set_farmer_peer: str,
    set_solver_peer: str,
    set_node_introducer: str,
    set_fullnode_port: str,
    set_harvester_port: str,
    set_log_level: str,
    log_systemd: str,
    enable_upnp: str,
    set_outbound_peer_count: str,
    set_peer_count: str,
    testnet: str,
    set_peer_connect_timeout: str,
    crawler_db_path: str | None,
    crawler_minimum_version_count: int | None,
    seeder_domain_name: str | None,
    seeder_nameserver: str | None,
    set_solver_trusted_peers_only: str,
) -> None:
    configure(
        ChiaCliContext.set_default(ctx).root_path,
        set_farmer_peer,
        set_solver_peer,
        set_node_introducer,
        set_fullnode_port,
        set_harvester_port,
        set_log_level,
        enable_upnp,
        set_outbound_peer_count,
        set_peer_count,
        testnet,
        set_peer_connect_timeout,
        crawler_db_path,
        crawler_minimum_version_count,
        seeder_domain_name,
        seeder_nameserver,
        set_solver_trusted_peers_only,
        log_systemd,
    )
