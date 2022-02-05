from pathlib import Path
import click
from chia.cmds.db_upgrade_func import db_upgrade_func
from chia.cmds.db_upgrade_alt_func import db_upgrade_alt_func


@click.group("db", short_help="Manage the blockchain database")
def db_cmd() -> None:
    pass


@db_cmd.command("upgrade", short_help="EXPERIMENTAL: upgrade a v1 database to v2")
@click.option("--input", default=None, type=click.Path(), help="specify input database file")
@click.option("--output", default=None, type=click.Path(), help="specify output database file")
@click.option(
    "--no-update-config",
    default=False,
    is_flag=True,
    help="don't update config file to point to new database. When specifying a "
    "custom output file, the config will not be updated regardless",
)
@click.pass_context
def db_upgrade_cmd(ctx: click.Context, no_update_config: bool, **kwargs) -> None:

    in_db_path = kwargs.get("input")
    out_db_path = kwargs.get("output")
    db_upgrade_func(
        Path(ctx.obj["root_path"]),
        None if in_db_path is None else Path(in_db_path),
        None if out_db_path is None else Path(out_db_path),
        no_update_config,
    )


@db_cmd.command("upgrade_alt", short_help="EXPERIMENTAL: upgrade v1 database to v2 - alternative approach")
@click.option("--input", default=None, type=click.Path(), help="specify input database file")
@click.option("--output", default=None, type=click.Path(), help="specify output database file")
@click.option("--hdd", default=False, is_flag=True, help="select if database is located on HDD device. (DEFAULT=false)")
@click.option(
    "--offline",
    default=False,
    is_flag=True,
    help="select to upgrade database with no active full node. (DEFAULT=false)",
)
@click.option(
    "--temp-store-path",
    default=None,
    type=click.Path(),
    help="specify path used as temporary db destination (Linux only)",
)
@click.option(
    "--check-only",
    default=False,
    is_flag=True,
    help="specify to check only if enough disk space is available for upgrade. (DEFAULT=false)",
)
@click.option(
    "--no-update-config",
    default=False,
    is_flag=True,
    help="don't update config file to point to new database. When specifying a "
    "custom output file, the config will not be updated regardless",
)
@click.pass_context
def db_upgrade_alt_cmd(
    ctx: click.Context, no_update_config: bool, offline: bool, hdd: bool, check_only: bool, **kwargs
) -> None:

    in_db_path = kwargs.get("input")
    out_db_path = kwargs.get("output")
    temp_path = kwargs.get("temp_store_path")
    db_upgrade_alt_func(
        Path(ctx.obj["root_path"]),
        None if in_db_path is None else Path(in_db_path),
        None if out_db_path is None else Path(out_db_path),
        no_update_config,
        offline,
        hdd,
        None if temp_path is None else Path(temp_path),
        check_only,
    )
