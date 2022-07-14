import click


@click.group("beta", hidden=True)
def beta_cmd() -> None:
    pass


@beta_cmd.command("enable", hidden=True)
@click.pass_context
def enable_cmd(ctx: click.Context) -> None:
    from chia.cmds.beta_funcs import configure_beta_test_mode

    configure_beta_test_mode(ctx.obj["root_path"], True)


@beta_cmd.command("disable", hidden=True)
@click.pass_context
def disable_cmd(ctx: click.Context) -> None:
    from chia.cmds.beta_funcs import configure_beta_test_mode

    configure_beta_test_mode(ctx.obj["root_path"], False)


@beta_cmd.command("prepare_submission", hidden=True)
@click.pass_context
def prepare_submission_cmd(ctx: click.Context) -> None:
    from chia.cmds.beta_funcs import prepare_submission

    prepare_submission(ctx.obj["root_path"])
