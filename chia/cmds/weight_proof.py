import asyncio
from pathlib import Path

import click

from chia.cmds.weight_proof_funcs import build_weight_proof_v2_database, check_weight_proof_v2_database


@click.group("wp", short_help="weight proof db cli")
def wp_cmd() -> None:
    pass


@wp_cmd.command("create", short_help="build db for v2 weight proofs")
@click.pass_context
def wp_build_v2_db_cmd(ctx: click.Context) -> None:
    try:
        asyncio.run(build_weight_proof_v2_database(Path(ctx.obj["root_path"])))
    except RuntimeError as e:
        print(f"FAILED: {e}")


@wp_cmd.command("check", short_help="check that the wp v2 segment db is populated")
@click.pass_context
def db_validate_v2_db_cmd(ctx: click.Context) -> None:
    try:
        v2db = asyncio.run(check_weight_proof_v2_database(Path(ctx.obj["root_path"])))
        print(f"weight proof v2 db: {v2db}")
    except RuntimeError as e:
        print(f"FAILED: {e}")
