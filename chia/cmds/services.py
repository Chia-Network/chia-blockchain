from __future__ import annotations

import click

from chia.cmds.cmd_classes import Context, argument, chia_command


@click.group(
    name="services",
    short_help="directly run Chia services",
    help="""Directly run Chia services without launching them through the daemon.  This
        can be useful sometimes during development for launching with a debugger, or
        when you want to use systemd or similar to manage the service processes.
    """,
)
def services_group() -> None:
    pass  # pragma: no cover


@chia_command(
    group=services_group,
    name="full-node",
    short_help="Start a full node",
    # presently unused
    help="Start a full node",
    add_help_option=False,
    ignore_unknown_options=True,
)
class FullNode:
    context: Context
    args: list[str] = argument(type=click.UNPROCESSED, multiple=True)

    def run(self) -> None:
        import sys

        from chia.server.start_full_node import main

        click_context = click.get_current_context()
        sys.argv = [click_context.command_path, *self.args]
        main(root_path=self.context["root_path"])


# full_node_command = get_chia_command_metadata(FullNode).command


# TODO: or instead of all other chia command changes, just add this and skip it
@services_group.command("full-node", add_help_option=False, context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def full_node_command(ctx: click.Context, args: list[str]) -> None:
    import sys

    from chia.server.start_full_node import main

    # hack since main() uses load_config_cli() which uses argparse
    sys.argv = [ctx.command_path, *args]
    main(root_path=ctx.obj["root_path"])
