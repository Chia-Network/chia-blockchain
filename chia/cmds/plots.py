import logging
import sys
from pathlib import Path

import click

from chia.plotting.check_plots import check_plots
from chia.plotting.create_plots import create_plots
from chia.plotting.plot_tools import add_plot_directory, get_plot_directories, remove_plot_directory
from chia.util.chia_logging import initialize_logging

DEFAULT_STRIPE_SIZE = 65536
log = logging.getLogger(__name__)


def show_plots(root_path: Path):
    print("Directories where plots are being searched for:")
    print("Note that subdirectories must be added manually")
    print(
        "Add with 'chia plots add -d [dir]' and remove with"
        + " 'chia plots remove -d [dir]'"
        + " Scan and check plots with 'chia plots check'"
    )
    print()
    for str_path in get_plot_directories(root_path):
        print(f"{str_path}")


@click.group("plots", short_help="Manage your plots")
@click.pass_context
def plots_cmd(ctx: click.Context):
    """Create, add, remove and check your plots"""
    root_path: Path = ctx.obj["root_path"]
    if not root_path.is_dir():
        raise RuntimeError("Please initialize (or migrate) your config directory with 'chia init'")
    initialize_logging("", {"log_stdout": True}, root_path)


@plots_cmd.command("create", short_help="Create plots")
@click.option("-k", "--size", help="Plot size", type=int, default=32, show_default=True)
@click.option("--override-k", help="Force size smaller than 32", default=False, show_default=True, is_flag=True)
@click.option("-n", "--num", help="Number of plots or challenges", type=int, default=1, show_default=True)
@click.option("-b", "--buffer", help="Megabytes for sort/plot buffer", type=int, default=4608, show_default=True)
@click.option("-r", "--num_threads", help="Number of threads to use", type=int, default=2, show_default=True)
@click.option("-u", "--buckets", help="Number of buckets", type=int, default=128, show_default=True)
@click.option(
    "-a",
    "--alt_fingerprint",
    type=int,
    default=None,
    help="Enter the alternative fingerprint of the key you want to use",
)
@click.option(
    "-c",
    "--pool_contract_address",
    type=str,
    default=None,
    help="Address of where the pool reward will be sent to. Only used if alt_fingerprint and pool public key are None",
)
@click.option("-f", "--farmer_public_key", help="Hex farmer public key", type=str, default=None)
@click.option("-p", "--pool_public_key", help="Hex public key of pool", type=str, default=None)
@click.option(
    "-t",
    "--tmp_dir",
    help="Temporary directory for plotting files",
    type=click.Path(),
    default=Path("."),
    show_default=True,
)
@click.option("-2", "--tmp2_dir", help="Second temporary directory for plotting files", type=click.Path(), default=None)
@click.option(
    "-d",
    "--final_dir",
    help="Final directory for plots (relative or absolute)",
    type=click.Path(),
    default=Path("."),
    show_default=True,
)
@click.option("-i", "--plotid", help="PlotID in hex for reproducing plots (debugging only)", type=str, default=None)
@click.option("-m", "--memo", help="Memo in hex for reproducing plots (debugging only)", type=str, default=None)
@click.option("-e", "--nobitfield", help="Disable bitfield", default=False, is_flag=True)
@click.option(
    "-x", "--exclude_final_dir", help="Skips adding [final dir] to harvester for farming", default=False, is_flag=True
)
@click.pass_context
def create_cmd(
    ctx: click.Context,
    size: int,
    override_k: bool,
    num: int,
    buffer: int,
    num_threads: int,
    buckets: int,
    alt_fingerprint: int,
    pool_contract_address: str,
    farmer_public_key: str,
    pool_public_key: str,
    tmp_dir: str,
    tmp2_dir: str,
    final_dir: str,
    plotid: str,
    memo: str,
    nobitfield: bool,
    exclude_final_dir: bool,
):
    class Params(object):
        def __init__(self):
            self.size = size
            self.num = num
            self.buffer = buffer
            self.num_threads = num_threads
            self.buckets = buckets
            self.stripe_size = DEFAULT_STRIPE_SIZE
            self.alt_fingerprint = alt_fingerprint
            self.pool_contract_address = pool_contract_address
            self.farmer_public_key = farmer_public_key
            self.pool_public_key = pool_public_key
            self.tmp_dir = Path(tmp_dir)
            self.tmp2_dir = Path(tmp2_dir) if tmp2_dir else None
            self.final_dir = Path(final_dir)
            self.plotid = plotid
            self.memo = memo
            self.nobitfield = nobitfield
            self.exclude_final_dir = exclude_final_dir

    if size < 32 and not override_k:
        print("k=32 is the minimun size for farming.")
        print("If you are testing and you want to use smaller size please add the --override-k flag.")
        sys.exit(1)
    elif size < 25 and override_k:
        print("Error: The minimum k size allowed from the cli is k=25.")
        sys.exit(1)

    create_plots(Params(), ctx.obj["root_path"])


@plots_cmd.command("check", short_help="Checks plots")
@click.option("-n", "--num", help="Number of plots or challenges", type=int, default=None)
@click.option(
    "-g",
    "--grep_string",
    help="Shows only plots that contain the string in the filename or directory name",
    type=str,
    default=None,
)
@click.option("-l", "--list_duplicates", help="List plots with duplicate IDs", default=False, is_flag=True)
@click.option("--debug-show-memo", help="Shows memo to recreate the same exact plot", default=False, is_flag=True)
@click.option("--challenge-start", help="Begins at a different [start] for -n [challenges]", type=int, default=None)
@click.pass_context
def check_cmd(
    ctx: click.Context, num: int, grep_string: str, list_duplicates: bool, debug_show_memo: bool, challenge_start: int
):
    check_plots(ctx.obj["root_path"], num, challenge_start, grep_string, list_duplicates, debug_show_memo)


@plots_cmd.command("add", short_help="Adds a directory of plots")
@click.option(
    "-d",
    "--final_dir",
    help="Final directory for plots (relative or absolute)",
    type=click.Path(),
    default=".",
    show_default=True,
)
@click.pass_context
def add_cmd(ctx: click.Context, final_dir: str):
    add_plot_directory(Path(final_dir), ctx.obj["root_path"])
    print(f'Added plot directory "{final_dir}".')


@plots_cmd.command("remove", short_help="Removes a directory of plots from config.yaml")
@click.option(
    "-d",
    "--final_dir",
    help="Final directory for plots (relative or absolute)",
    type=click.Path(),
    default=".",
    show_default=True,
)
@click.pass_context
def remove_cmd(ctx: click.Context, final_dir: str):
    remove_plot_directory(Path(final_dir), ctx.obj["root_path"])
    print(f'Removed plot directory "{final_dir}".')


@plots_cmd.command("show", short_help="Shows the directory of current plots")
@click.pass_context
def show_cmd(ctx: click.Context):
    show_plots(ctx.obj["root_path"])
