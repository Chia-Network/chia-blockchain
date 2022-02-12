import sys
from datetime import datetime
from decimal import Decimal
from typing import Callable, List, Optional, Dict

import aiohttp

from chia.cmds.units import units
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.server.start_wallet import SERVICE_NAME
from chia.types.coin_record import CoinRecord
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16


async def execute_with_node(node_rpc_port: Optional[int], extra_params: Dict, function: Callable) -> None:
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if node_rpc_port is None:
            node_rpc_port = config["full_node"]["rpc_port"]
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(node_rpc_port), DEFAULT_ROOT_PATH, config)
        await function(extra_params, node_client)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(
                f"Connection error. Check if the node is running at {node_rpc_port}. "
                "You can run the node via:\n\tchia start node"
            )
        else:
            print(f"Exception from 'node' {e}")
    node_client.close()
    await node_client.await_closed()


def print_transaction(coin_record: CoinRecord, verbose: bool, name, address_prefix: str, mojo_per_unit: int) -> None:
    if verbose:
        print(coin_record)
    else:
        chia_amount = Decimal(int(coin_record.coin.amount)) / mojo_per_unit
        to_address = encode_puzzle_hash(coin_record.coin.puzzle_hash, address_prefix)
        print(f"Coin {coin_record.name}")
        print(f"Status: {'Confirmed' if coin_record.confirmed_block_index != 0 else 'Pending'}")
        print(f"Amount {'sent'}: {chia_amount} {name}")
        print(f"To address: {to_address}")
        print("Created at:", datetime.fromtimestamp(float(coin_record.timestamp)).strftime("%Y-%m-%d %H:%M:%S"))
        print("")


async def get_transactions(args: dict, node_client: FullNodeRpcClient) -> None:
    paginate = args["paginate"]
    puzzle_hash = args["ph"]
    if paginate is None:
        paginate = sys.stdout.isatty()
    coin_records: List[CoinRecord] = await node_client.get_coin_records_by_puzzle_hash(puzzle_hash)
    if len(coin_records) == 0:
        print("There are no transactions to this address")

    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    offset = args["offset"]
    # these might need to be changed for a cat wallet.
    name = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"].upper()
    mojo_per_unit = units["chia"]
    num_per_screen = 5 if paginate else len(coin_records)
    for i in range(offset, len(coin_records), num_per_screen):
        for j in range(0, num_per_screen):
            if i + j >= len(coin_records):
                break
            print_transaction(
                coin_records[i + j],
                verbose=(args["verbose"] > 0),
                name=name,
                address_prefix=address_prefix,
                mojo_per_unit=mojo_per_unit,
            )
        if i + num_per_screen >= len(coin_records):
            return None
        print("Press q to quit, or c to continue")
        while True:
            entered_key = sys.stdin.read(1)
            if entered_key == "q":
                return None
            elif entered_key == "c":
                break
