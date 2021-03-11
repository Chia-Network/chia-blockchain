"""
Creating Atomic Spends

These functions create puzzles, solutions, and spend bundles for creating HTLCs
or Hash Time Locked Contracts.

The expected use is for two parties to execute the following steps:

1) A "source" locks up their coins behind a "safe" puzzle using generate_safe_puzzle
2) The source informs the "target" of the args used to create the puzzle
3) The target creates a puzzle using those args and hashes it to verify that a coin
   locked up with that puzzle hash is present on the blockchain
4) The target creates a safe puzzle using:
    a) Their pubkey as source_pubkey
    b) The other party's pubkey as target_pubkey
    c) A claim height LOWER than the claim height the other party used (with enough
       of a difference that they can feel confident getting a claim back confirmed
       before the other party can claim their own coins back)
    d) The SAME preimage_hash that the other party sent with the original safe transaction
5) The target informs the source that the coins have been locked up
6) The source claims the target's coins, revealing the preimage in the process
7) The target claims the source's coins, using that same preimage (can be retrieved
   through get_preimage_from_claim_solution)

"""
from typing import List

from blspy import PrivateKey, G1Element, AugSchemeMPL

from src.types.blockchain_format.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.blockchain_format.coin import Coin
from src.types.condition_opcodes import ConditionOpcode

from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    solution_for_delegated_puzzle,
    puzzle_for_synthetic_public_key,
    puzzle_for_public_key_and_hidden_puzzle_hash,
)

from src.wallet.puzzles.load_clvm import load_clvm

MOD = load_clvm("atomic_swap.clvm")

DEFAULT_HIDDEN_PUZZLE = Program.from_bytes(bytes.fromhex("ff0980"))
DEFAULT_HIDDEN_PUZZLE_HASH = DEFAULT_HIDDEN_PUZZLE.get_tree_hash()  # this puzzle `(x)` always fails


# generates the transaction that locks coins up with either the sources signature at a specified claim_height
# OR the corresponding preimage and a signature from the target
def generate_safe_puzzle(
    source_pubkey: G1Element, target_pubkey: G1Element, claim_height: int, preimage_hash: bytes32
) -> Program:
    return MOD.curry(bytes(source_pubkey), bytes(target_pubkey), claim_height.to_bytes(4, "big"), preimage_hash)


def get_safe_transaction_puzzle_hash(
    source_pubkey: G1Element, target_pubkey: G1Element, claim_height: int, preimage_hash: bytes32
) -> bytes32:
    return generate_safe_puzzle(source_pubkey, target_pubkey, claim_height, preimage_hash).get_tree_hash()


def get_standard_puzzle_with_safe(
    source_pubkey: G1Element, target_pubkey: G1Element, claim_height: int, preimage_hash: bytes32
) -> Program:
    return puzzle_for_public_key_and_hidden_puzzle_hash(
        (source_pubkey + target_pubkey),
        get_safe_transaction_puzzle_hash(source_pubkey, target_pubkey, claim_height, preimage_hash)
    )


def get_standard_puzzle_hash_with_safe(
    source_pubkey: G1Element, target_pubkey: G1Element, claim_height: int, preimage_hash: bytes32
) -> Program:
    return get_standard_puzzle_with_safe(source_pubkey,target_pubkey,claim_height,preimage_hash).get_tree_hash()


# target == 0 will act as though this is the source attempting to claim it back,
# all other values will require a valid preimage
def generate_safe_solution(
    preimage: bytes32, target: int, delegated_puzzle: Program, delegated_solution: Program
) -> Program:
    return Program.to([preimage, target, delegated_puzzle, delegated_solution])


def get_preimage_from_claim_solution(solution: Program) -> str:
    return solution.as_python()[0].decode("utf-8")


def create_safe_spend_bundle_from_standard_coins(
    coins: List[Coin],
    synthetic_sk: PrivateKey,
    lock_amount: int,
    source_pubkey: G1Element,
    target_pubkey: G1Element,
    claim_height: int,
    preimage_hash: bytes32,
) -> SpendBundle:

    coin_names = []
    for coin in coins:
        coin_names.append(coin.name())

    puzzle_reveal = puzzle_for_synthetic_public_key(synthetic_sk.get_g1())
    create_coin_program = Program.to(
        (
            1,
            [
                [
                    ConditionOpcode.CREATE_COIN,
                    get_standard_puzzle_with_safe(source_pubkey, target_pubkey, claim_height, preimage_hash),
                    lock_amount,
                ]
            ],
        )
    )
    solution_reveal = solution_for_delegated_puzzle(create_coin_program, Program.to(0))
    burn_solution = Program.from_bytes(bytes.fromhex("ff80ffff0180ff8080"))
    burn_solution_delegated_puzzle_hash = Program.from_bytes(bytes.fromhex("ff0180")).get_tree_hash()

    safe_creation_sig = AugSchemeMPL.sign(synthetic_sk, bytes(create_coin_program.get_tree_hash()) + coin_names[0])
    signatures = [safe_creation_sig]
    if len(coin_names) > 1:
        for coin_name in coin_names[1:]:
            signatures.append(AugSchemeMPL.sign(synthetic_sk, bytes(burn_solution_delegated_puzzle_hash) + coin_name))
    sig = AugSchemeMPL.aggregate(signatures)

    spend_bundle = {"aggregated_signature": str(sig)}
    coin_solutions = []
    first_coin = True
    for coin in coins:
        coin_solution = {
            "coin": {
                "parent_coin_info": str(coin.parent_coin_info),
                "puzzle_hash": str(coin.puzzle_hash),
                "amount": coin.amount,
            },
            "puzzle_reveal": str(puzzle_reveal),
            "solution": str(solution_reveal) if first_coin else str(burn_solution),
        }
        coin_solutions.append(coin_solution)
        first_coin = False
    spend_bundle["coin_solutions"] = str(coin_solutions)

    return SpendBundle.from_json_dict(spend_bundle)


def create_claim_spend_bundle(
    safe: Coin, claim_sk: PrivateKey, safe_puzzle: Program, safe_solution: Program, delegated_puzzle_hash: bytes32
) -> SpendBundle:

    sig = AugSchemeMPL.sign(claim_sk, delegated_puzzle_hash + safe.name())

    coin_solution = {
        "coin": {
            "parent_coin_info": str(safe.parent_coin_info),
            "puzzle_hash": str(safe.puzzle_hash),
            "amount": safe.amount,
        },
        "puzzle_reveal": str(safe_puzzle),
        "solution": str(safe_solution),
    }

    spend_bundle = {"aggregated_signature": str(sig), "coin_solutions": [coin_solution]}

    return SpendBundle.from_json_dict(spend_bundle)


# Testing

# Setup
# from src.util.condition_tools import parse_sexp_to_conditions
# from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import calculate_synthetic_secret_key
# from src.wallet.derive_keys import master_sk_to_wallet_sk
#
# safe_puzzle = generate_safe_puzzle(
#     G1Element.from_bytes(bytes.fromhex("source_public_key")),
#     G1Element.from_bytes(bytes.fromhex("target_public_key")),
#     50256, #height at which source can claim this transaction back
#     bytes.fromhex("107661134F21FC7C02223D50AB9EB3600BC3FFC3712423A1E47BB1F9A9DBF55F") #hash of the string 'preimage'
# )
# print(safe_puzzle.get_tree_hash())

# Test opcodes for source claim back
# source_solution = generate_safe_solution("",0,Program.to((1,[[ConditionOpcode.CREATE_COIN,0x4,50]])),Program.to(0))
# cost, result = safe_puzzle.run_with_cost(source_solution)
# for sexp in result.as_iter():
#     items = sexp.as_python()
#     opcode = ConditionOpcode(items[0])
#     print(opcode)
#     print(int.from_bytes(items[1],"big"))

# Test opcodes for target with correct preimage
# target_correct_solution = generate_safe_solution(
#         "preimage",
#         1,
#         Program.to((1,[[ConditionOpcode.CREATE_COIN,0x4,50]])),
#         Program.to(0)
#     )
# cost, result = safe_puzzle.run_with_cost(target_correct_solution)
# for sexp in result.as_iter():
#     items = sexp.as_python()
#     opcode = ConditionOpcode(items[0])
#     print(opcode)
#     print(int.from_bytes(items[1],"big"))

# Test exception with incorrect preimage
# target_incorrect_solution = generate_safe_solution(
#         "incorrect",
#         1,
#         Program.to((1,[[ConditionOpcode.CREATE_COIN,0x4,50]])),
#         Program.to(0)
#     )
# cost, result = safe_puzzle.run_with_cost(target_incorrect_solution)
# for sexp in result.as_iter():
#     items = sexp.as_python()
#     opcode = ConditionOpcode(items[0])
#     print(opcode)
#     print(int.from_bytes(items[1],"big"))

# Test the creation of a "safe"
# create_safe_spend_bundle_from_standard_coins(
#     [
#         #Fill in custom info or just replace with a Coin obj
#         Coin.from_json_dict({
#             "amount" : "11000000000000",
#             "parent_coin_info" : "0xpci",
#             "puzzle_hash" : "0xdelegatedorhiddenpuzzlehash"
#         })
#     ],
#       calculate_synthetic_secret_key(
#         master_sk_to_wallet_sk(PrivateKey.from_bytes(bytes.fromhex("0xmastersk")),0),
#         DEFAULT_HIDDEN_PUZZLE_HASH
#       ),
#     10500000000000, #replace with amount to be claimed back
#     G1Element.from_bytes(bytes.fromhex("0xsourcepubkey")),
#     G1Element.from_bytes(bytes.fromhex("0xtargetpubkey")),
#     6000, #replace with desired claim height
#     bytes.fromhex("107661134F21FC7C02223D50AB9EB3600BC3FFC3712423A1E47BB1F9A9DBF55F") #hash of the string 'preimage'
# )

# Test claiming funds from a safe
# create_claim_spend_bundle(
#     #Fill in custom info or just replace with a Coin obj
#     Coin.from_json_dict({
#         "amount" : "10500000000000",
#         "parent_coin_info" : "0xpci",
#         "puzzle_hash" : "0xatomicsafepuzzlehash"
#     }),
#     master_sk_to_wallet_sk(PrivateKey.from_bytes(bytes.fromhex("0xmastersk")),0),
#     generate_safe_puzzle(
#         G1Element.from_bytes(bytes.fromhex("0xsourcepubkey")),
#         G1Element.from_bytes(bytes.fromhex("0xtargetpubkey")),
#         6000, #replace with desired claim height
#         bytes.fromhex("107661134F21FC7C02223D50AB9EB3600BC3FFC3712423A1E47BB1F9A9DBF55F") #hash of string 'preimage'
#     ),
#     generate_safe_solution(
#         "", #replace with preimage if you are attempting to claim this with a preimage (as the "target")
#         0, #replace with 1 if you are attempting to claim this with a preimage (as the "target")
#         Program.to((1,[[ConditionOpcode.CREATE_COIN,
#             bytes.fromhex("0xdelegatedpuzzlehash"),
#             10000000000000]])), #replace with desired amount to claim
#         Program.to(0)
#     ),
#     #This gets the hash of the program that was passed in to generate_safe_solution above for signing
#     Program.to((1,[[ConditionOpcode.CREATE_COIN,
#         bytes.fromhex("0xdelegatedpuzzlehash"),
#         10000000000000]])).get_tree_hash(),
# )
