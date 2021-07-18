import click


@click.group("farm", short_help="Manage your farm")
def farm_cmd() -> None:
    pass


@farm_cmd.command("summary", short_help="Summary of farming information")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-hp",
    "--harvester-rpc-port",
    help=(
        "Set the port where the Harvester is hosting the RPC interface"
        "See the rpc_port under harvester in config.yaml"
    ),
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-fp",
    "--farmer-rpc-port",
    help=(
        "Set the port where the Farmer is hosting the RPC interface. " "See the rpc_port under farmer in config.yaml"
    ),
    type=int,
    default=None,
    show_default=True,
)
def summary_cmd(rpc_port: int, wallet_rpc_port: int, harvester_rpc_port: int, farmer_rpc_port: int) -> None:
    from .farm_funcs import summary
    import asyncio

    asyncio.run(summary(rpc_port, wallet_rpc_port, harvester_rpc_port, farmer_rpc_port))


@farm_cmd.command("challenges", short_help="Show the latest challenges")
@click.option(
    "-fp",
    "--farmer-rpc-port",
    help="Set the port where the Farmer is hosting the RPC interface. See the rpc_port under farmer in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-l",
    "--limit",
    help="Limit the number of challenges shown. Use 0 to disable the limit",
    type=click.IntRange(0),
    default=20,
    show_default=True,
)
def challenges_cmd(farmer_rpc_port: int, limit: int) -> None:
    from .farm_funcs import challenges
    import asyncio

    asyncio.run(challenges(farmer_rpc_port, limit))


@farm_cmd.command("uploadfarmerdata", short_help="Upload the farm summary and challenges data to community.chivescoin.org, and you can query the data in this site.")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-hp",
    "--harvester-rpc-port",
    help=(
        "Set the port where the Harvester is hosting the RPC interface"
        "See the rpc_port under harvester in config.yaml"
    ),
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-fp",
    "--farmer-rpc-port",
    help=(
        "Set the port where the Farmer is hosting the RPC interface. " "See the rpc_port under farmer in config.yaml"
    ),
    type=int,
    default=None,
    show_default=True,
)
def uploadfarmerdata_cmd(rpc_port: int, wallet_rpc_port: int, harvester_rpc_port: int, farmer_rpc_port: int) -> None:
    print("If has 'ModuleNotFoundError: No module named requests', please execute the command in cmd:'pip install requests', and back to restart it.")
    from .farm_funcs import summary,challenges,uploadfarmerdata
    import asyncio
    import requests
    import time
    import json
    from datetime import datetime
    while 1==1:
        FarmerSatus = asyncio.run(uploadfarmerdata(rpc_port, wallet_rpc_port, harvester_rpc_port, farmer_rpc_port))
        FarmerSatusJson = json.dumps(FarmerSatus)
        print('------------------------------------------------------------------')
        print(datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"))
        print(f"Upload the farm summary and challenges data to community.chivescoin.org, and you can query the data in this site.")
        content = requests.post('https://community.chivescoin.org/farmerinfor/uploaddata.php', data={'FarmerSatus':FarmerSatusJson}).json()
        print(content)
        time.sleep(5)

