import asyncio
import argparse
import aiohttp
from src.rpc.rpc_client import RpcClient
from src.util.byte_types import hexstr_to_bytes


def str2bool(v: str) -> bool:
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


async def main():
    parser = argparse.ArgumentParser(description="block-by-header.py.")

    parser.add_argument(
        "-b",
        "--block_header_hash",
        help="Block header hash string",
        type=str,
        default="",
    )
    parser.add_argument(
        "-s",
        "--state",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
        help="Get state",
    )
    parser.add_argument(
        "-c",
        "--connections",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
        help="Get state",
    )

    parser.add_argument(
        "-p",
        "--rpc-port",
        help="RPC port that full node is exposing",
        type=int,
        default=8555,
    )

    args = parser.parse_args()

    print(args)

    try:
        client = await RpcClient.create(args.rpc_port)

        state = await client.get_blockchain_state()

        # TODO: Add other rpc calls
        # TODO: pretty print response
        if args.state:
            state = await client.get_blockchain_state()
            print(state)
        if args.connections:
            connections = await client.get_connections()
            for connection in connections:
                print(connection)
        elif args.block_header_hash != "":
            block = await client.get_block(hexstr_to_bytes(args.block_header_hash))
            print(block)

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {args.rpc_port}")
        else:
            print(f"Exception {e}")

    client.close()
    await client.await_closed()


asyncio.run(main())
