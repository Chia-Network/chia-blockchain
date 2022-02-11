from pathlib import Path
import click
from chia.cmds.db_upgrade_func import db_upgrade_func


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
@click.option(
    "--offline",
    default=False,
    is_flag=True,
    help="open the input database in offline-mode. no other process may use "
    "the database file, you must not have a full node running against it. This may "
    "provide some performance improvements",
)
@click.option(
    "--vacuum",
    default=False,
    is_flag=True,
    help="vacuum the input database in an attempt to improve performance when "
    "converting. This is only valid when also specifying --offline.",
)
@click.pass_context
def db_upgrade_cmd(ctx: click.Context, no_update_config: bool, offline: bool, vacuum: bool, **kwargs) -> None:

    if vacuum and not offline:
        print("--vacuum is only valid when also specifying --offline")
        raise RuntimeError("invalid command line option")

    in_db_path = kwargs.get("input")
    out_db_path = kwargs.get("output")
    db_upgrade_func(
        Path(ctx.obj["root_path"]),
        None if in_db_path is None else Path(in_db_path),
        None if out_db_path is None else Path(out_db_path),
        no_update_config=no_update_config,
        offline=offline,
        vacuum=vacuum,
    )


if __name__ == "__main__":
    from chia.util.default_root import DEFAULT_ROOT_PATH

    db_upgrade_func(DEFAULT_ROOT_PATH)
