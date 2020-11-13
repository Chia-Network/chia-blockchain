# tx command imports
import json
import asyncio
from src.util.byte_types import hexstr_to_bytes
from clvm_tools import binutils

# blspy
from blspy import G1Element, G2Element

# transaction imports
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.types.coin_solution import CoinSolution
from src.types.spend_bundle import SpendBundle
from src.types.coin import Coin
from src.types.coinwithpubkey import CoinWithPubkey
from src.util.ints import uint64
from typing import List, Set

from src.wallet.puzzles.puzzle_utils import (
    make_assert_my_coin_id_condition,
    make_assert_time_exceeds_condition,
    make_assert_coin_consumed_condition,
    make_create_coin_condition,
    make_assert_fee_condition,
)
from src.wallet.puzzles.p2_delegated_puzzle import (
    puzzle_for_pk,
    solution_for_conditions,
)

from src.util.debug_spend_bundle import debug_spend_bundle

# Connect to actual wallet
from src.rpc.wallet_rpc_client import WalletRpcClient


# TODO: From wallet/wallet.py: refactor
def make_solution(primaries=None, min_time=0, me=None, consumed=None, fee=0):
    assert fee >= 0
    condition_list = []
    if primaries:
        for primary in primaries:
            condition_list.append(
                make_create_coin_condition(primary["puzzlehash"], primary["amount"])
            )
    if consumed:
        for coin in consumed:
            condition_list.append(make_assert_coin_consumed_condition(coin))
    if min_time > 0:
        condition_list.append(make_assert_time_exceeds_condition(min_time))
    if me:
        condition_list.append(make_assert_my_coin_id_condition(me["id"]))
    if fee:
        condition_list.append(make_assert_fee_condition(fee))
    print(condition_list)
    return solution_for_conditions(condition_list)


class SpendRequest:
    puzzle_hash: bytes32
    amount: uint64

    def __init__(self, ph, amt):
        self.puzzle_hash = ph
        self.amount = amt


def create_unsigned_transaction(
    coins: Set[CoinWithPubkey] = None,  # Set[CoinWithPuzzle] = None,
    spend_requests: List[SpendRequest] = None,
    validate=True,
) -> List[CoinSolution]:
    """
    Generates a unsigned transaction in form of List(Puzzle, Solutions)
    """

    if coins is None or len(coins) < 1:
        raise (ValueError("tx create requires one or more input_coins"))
    assert len(coins) > 0
    # We treat the first coin as the origin
    # For simplicity, only the origin coin creates outputs
    origin = coins.pop()
    outputs = []
    input_value = sum([coin.amount for coin in coins]) + origin.amount
    sent_value = 0
    if spend_requests is not None:
        sent_value = sum([req.amount for req in spend_requests])
        for request in spend_requests:
            outputs.append({"puzzlehash": request.puzzle_hash, "amount": request.amount})
    if validate and sent_value != input_value:
        raise (
            ValueError(
                f"input amounts ({input_value}) do not equal outputs ({sent_value})"
            )
        )

    spends: List[CoinSolution] = []

    # Eventually, we will support specifying the puzzle directly in the
    # input to create_unsigned_transaction (viaCoinWithPuzzle).
    # For now, we specify a pubkey, and use the "standard transaction"
    origin_puzzle = puzzle_for_pk(origin.pubkey)
    assert origin_puzzle.get_tree_hash() == origin.puzzle_hash

    solution = make_solution(primaries=outputs, fee=0)
    puzzle_solution_pair = Program.to([origin_puzzle, solution])
    spends.append(CoinSolution(origin, puzzle_solution_pair))

    for coin in coins:
        print(f"processing coin {coin}")
        solution = make_solution()
        puzzle = puzzle_for_pk(coin.pubkey)
        puzzle_solution_pair = Program.to([puzzle, solution])
        spends.append(CoinSolution(coin, puzzle_solution_pair))

    return spends


def create_unsigned_tx_from_json(json_tx):
    j = json.loads(json_tx)
    spends = []
    for s in j["spends"]:
        if "spend_requests" in s:
            input_coins_json = s["input_coins"]
            spend_requests_json = s["spend_requests"]  # Output addresses and amounts
            pubkey = G1Element.from_bytes(hexstr_to_bytes(input_coins_json[0]["pubkey"]))
            print("PUB", type(pubkey), pubkey)
            input_coins = [
                CoinWithPubkey(
                    hexstr_to_bytes(c["parent_id"]),
                    hexstr_to_bytes(c["puzzle_hash"]),
                    c["amount"],
                    pubkey
                )
                for c in input_coins_json
            ]
            spend_requests = [
                SpendRequest(hexstr_to_bytes(s["puzzle_hash"]), s["amount"])
                for s in spend_requests_json
            ]
            print(input_coins, spend_requests)
            spends.extend(create_unsigned_transaction(input_coins, spend_requests))
        elif "solution" in s:
            input_coin = Coin(
                hexstr_to_bytes(s["input_coin"]["parent_id"]),
                hexstr_to_bytes(s["input_coin"]["puzzle_hash"]),
                uint64(s["input_coin"]["amount"]),
            )
            puzzle_reveal = Program(binutils.assemble(s["puzzle_reveal"]))
            assert puzzle_reveal.get_tree_hash() == input_coin.puzzle_hash
            solution = Program(binutils.assemble(s["solution"]))
            spends.append(
                CoinSolution(input_coin, Program.to([puzzle_reveal, solution]))
            )

    spend_bundle = SpendBundle(spends, G2Element.infinity())
    debug_spend_bundle(spend_bundle)
    # output = { "spends": spends }

    # TODO: Object of type CoinSolution is not JSON serializable
    # print(json.dumps(output))


# Command line handling

command_list = [
    "create",
    "verify",
    "sign",
    "push",
    "encode",
    "decode",
    "view-coins",
]


def help_message():
    print(
        "usage: chia tx command\n"
        + f"command can be any of {command_list}\n"
        + "\n"
        + "chia tx create amount puzzle_hash fee origin_id [coins]\n"
    )


def make_parser(parser):
    parser.add_argument(
        "command",
        help=f"Command can be any one of {command_list}",
        type=str,
        nargs="?",
    )

    parser.add_argument("json_tx", help="json encoded transaction", type=str)
    parser.set_defaults(function=handler)
    parser.print_help = lambda self=parser: help_message()


async def push_tx(args, parser):
    print()
    return


async def view_coins(args, parser):
    wrpc = await WalletRpcClient.create("127.0.0.1", 9256)
    coins = await wrpc.get_spendable_coins(1)
    print(coins)
    wrpc.close()
    return


def handler(args, parser):
    # if args.command is None or len(args.command) < 1:
    #     help_message()
    #     parser.exit(1)

    command = args.command
    if command not in command_list:
        help_message()
        parser.exit(1)

    if command == "create":
        if args.json_tx is None:
            print("create command is missing json_tx")
            help_message()
            parser.exit(1)
        create_unsigned_tx_from_json(args.json_tx)
    elif command == "verify":
        print()
    elif command == "sign":
        print()
    elif command == "push":
        return asyncio.get_event_loop().run_until_complete(push_tx(args, parser))
    elif command == "encode":
        print()
    elif command == "decode":
        print()
    elif command == "view-coins":
        return asyncio.get_event_loop().run_until_complete(view_coins(args, parser))
    else:
        print(f"command '{command}' is not recognised")
        parser.exit(1)
