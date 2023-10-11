from __future__ import annotations

from pathlib import Path

import click

from chia.cmds.init_funcs import chia_init

CHIA_PATH = Path.home() / ".chia"
CONTEXT_FILE = CHIA_PATH / "context"


# Function to list available contexts
def list_contexts():
    contexts = [dir.name for dir in CHIA_PATH.iterdir() if dir.is_dir()]
    print("Available contexts:")
    print("\n".join(contexts))


# Function to get the current context
def get_context():
    with open(CONTEXT_FILE, "r") as file:
        context = file.read().strip()
    print(f"Current context: {context}")
    return context


# Function to set a new context
def set_context(new_context):
    with open(CONTEXT_FILE, "w") as file:
        file.write(new_context)
    print(f"Context set to: {new_context}")


def create_context(context_type, v1_db=False):
    context_dir = CHIA_PATH / context_type
    if context_dir.is_dir():
        print(f"{context_type} context already exists.")
        return
    context_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created {context_type} context directory.")
    original_context = get_context()
    set_context(context_type)
    print(f"Temporarily set to {context_type} context.")

    # Define the root path for the new context
    root_path = Path.home() / ".chia" / context_type

    # Set the parameters for initialization
    should_check_keys = True
    fix_ssl_permissions = False
    testnet = True

    # Call the chia_init function
    chia_init(
        root_path=root_path,
        should_check_keys=should_check_keys,
        fix_ssl_permissions=fix_ssl_permissions,
        testnet=testnet,
        v1_db=v1_db,
    )

    set_context(original_context)
    print(f"Switched back to {original_context} context.")


def get_default_root_path():
    with open(CONTEXT_FILE, "r") as file:
        context = file.read().strip()
    return Path.home() / ".chia" / context


@click.command("context", short_help="Manage Chia blockchain contexts.")
@click.option("-l", "--list", "list_option", is_flag=True, help="List available contexts.")
@click.option("-g", "--get", "get_option", is_flag=True, help="Get the current context.")
@click.option("-s", "--set", "set_option", type=str, help="Set a new context.")
@click.option(
    "-c",
    "--create",
    "create_option",
    type=click.Choice(["testnet"]),
    help="Create a new context. Valid argument: testnet.",
)
@click.pass_context
def context_cmd(ctx, list_option, get_option, set_option, create_option):
    """Manage Chia blockchain contexts. Contexts are different networks, such as mainnet, testnets, or custom configurations, that are differentiated by a unique Genesis Puzzle Hash."""
    if list_option:
        list_contexts()
    elif get_option:
        get_context()
    elif set_option:
        set_context(set_option)
    elif create_option:
        create_context(create_option)
    else:
        click.echo(ctx.get_help())
