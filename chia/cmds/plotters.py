import click
from chia.plotters.plotters import call_plotters


def usage():
    print("""Usage: chia plotters COMMAND [ARGS]...

    Run plotters, show plotter versions

Options:
  -h, --help  Show this message and exit

Commands:
  version    Show installed plotter versions
  chiapos    Create a plot with the default chia plotter
  madmax     Create a plot with madMAx
  bladebit   Create a plot with bladebit
  bladebit2  Create a plot with bladebit2""")


@click.command(
    "plotters",
    short_help="Advanced plotting options",
    context_settings={"ignore_unknown_options": True},
    add_help_option=False,
)
@click.pass_context
@click.argument("args", nargs=-1)
def plotters_cmd(ctx: click.Context, args):
    if len(args) < 1 or args[0] in ["-h", "--help"]:
        usage()
        return

    call_plotters(ctx.obj["root_path"], args)
