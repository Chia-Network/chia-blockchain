import click

from pathlib import Path
import logging
from src.plotting.plot_tools import (
    get_plot_directories,
)
from src.plotting.create_plots import create_plots
from src.plotting.check_plots import check_plots
from src.util.logging import initialize_logging


log = logging.getLogger(__name__)

def show_plots(root_path):
    print("Directories where plots are being searched for:")
    print("Note that subdirectories must be added manually.")
    print(
        "Add with 'chia plots add -d [dir]' and remove with"
        + " 'chia plots remove -d [dir]'."
        + " Scan and check plots with 'chia plots check'"
    )
    print()
    for str_path in get_plot_directories(root_path):
        print(f"{str_path}")


@click.group('plots', short_help="manage your plots")
@click.pass_context
def plots_cmd(ctx):
    """Create, add, remove and check your plots"""
    root_path: Path = ctx.obj["root_path"]
    if not root_path.is_dir():
        raise RuntimeError("Please initialize (or migrate) your config directory with chia init.")
    initialize_logging("", {"log_stdout": True}, root_path)

@plots_cmd.command('create', short_help="creates plots")
@click.option("-k", "--size", help="Plot size", type=int, default=32, show_default=True)
@click.option("-n", "--num", help="Number of plots or challenges", type=int, default=1, show_default=True)
@click.option("-b", "--buffer", help="Megabytes for sort/plot buffer", type=int, default=4608, show_default=True)
@click.option("-r", "--num_threads", help="Number of threads to use", type=int, default=2, show_default=True)
@click.option("-u", "--buckets", help="Number of buckets", type=int, default=0)
@click.option("-s", "--stripe_size", help="Stripe size", type=int, default=0)
@click.option( "-a", "--alt_fingerprint", type=int, default=None, help="Enter the alternative fingerprint of the key you want to use",)
@click.option( "-c", "--pool_contract_address", type=str, default=None, help="Address of where the pool reward will be sent to. Only used if alt_fingerprint and pool public key are None",)
@click.option( "-f", "--farmer_public_key", help="Hex farmer public key", type=str, default=None,)
@click.option("-p", "--pool_public_key", help="Hex public key of pool", type=str, default=None)
@click.option( "-t", "--tmp_dir", help="Temporary directory for plotting files", type=Path, default=Path("."), show_default=True)
@click.option( "-2", "--tmp2_dir", help="Second temporary directory for plotting files", type=Path, default=None,)
@click.option( "-d", "--final_dir", help="Final directory for plots (relative or absolute)", type=Path, default=Path("."), show_default=True)
@click.option( "-i", "--plotid", help="PlotID in hex for reproducing plots (debugging only)", type=str, default=None,)
@click.option( "-m", "--memo", help="Memo in hex for reproducing plots (debugging only)", type=str, default=None,)
@click.option( "-e", "--nobitfield", help="Disable bitfield", default=False, is_flag=True)
@click.option( "-x", "--exclude_final_dir", help="Skips adding [final dir] to harvester for farming", default=False, is_flag=True)
@click.pass_context
def create_cmd(ctx, size, num, buffer, num_threads, buckets, stripe_size, alt_fingerprint, pool_contract_address, farmer_public_key, pool_public_key, tmp_dir, tmp2_dir, final_dir, plotid, memo, nobitfield, exclude_final_dir):
    class Params(object):
        pass
    params = Params()
    params.size = size
    params.num = num
    params.buffer = buffer
    params.num_threads = num_threads
    params.buckets = buckets
    params.stripe_size = strip_size
    params.alt_fingerprint = alt_fingerprint
    params.pool_contract_address = pool_contract_address
    params.farmer_public_key = farmer_public_key
    params.pool_public_key = pool_public_key
    params.tmp_dir = tmp_dir
    params.tmp2_dir = tmp2_dir
    params.final_dir = final_dir
    params.plotid = plotid
    params.memo = memo
    params.nobitfield = nobitfield
    params.exclude_final_dir = exclude_final_dir
    create_plots(params, ctx.obj["root_path"])

@plots_cmd.command('check', short_help="checks plots")
@click.option("-n", "--num", help="Number of plots or challenges", type=int, default=None)
@click.option( "-g", "--grep_string", help="Shows only plots that contain the string in the filename or directory name", type=str, default=None,)
@click.option( "-l", "--list_duplicates", help="List plots with duplicate IDs", default=False, is_flag=True)
@click.option( "--debug-show-memo", help="Shows memo to recreate the same exact plot", default=False, is_flag=True)
@click.option( "--challenge-start", help="Begins at a different [start] for -n [challenges]", type=int, default=None,)
@click.pass_context
def check_cmd(ctx, num, grep_string, list_duplicates, debug_show_memo, challenge_start):
    check_plots(ctx.obj["root_path"], num, challenge_start, grep_string, list_duplicates, debug_show_memo)

@plots_cmd.command('add', short_help="adds a directory of plots")
@click.option("-d", "--final_dir", help="Final directory for plots (relative or absolute)", type=click.Path(), default=".", show_default=True)
@click.pass_context
def add_cmd(ctx, final_dir):
    add_plot_directory(final_dir, ctx.obj['root_path'])

@plots_cmd.command('remove', short_help="removes a directory of plots from config")
@click.option("-d", "--final_dir", help="Final directory for plots (relative or absolute)", type=click.Path(), default=".", show_default=True)
@click.pass_context
def remove_cmd(ctx, final_dir):
    remove_plot_directory(final_dir, ctx.obj['root_path'])

@plots_cmd.command('show', short_help="shows the directory of current plots")
@click.pass_context
def show_cmd(ctx):
    show_plots(ctx.obj['root_path'])
