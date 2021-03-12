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

from blspy import G1Element

from src.types.blockchain_format.program import Program
from src.types.blockchain_format.sized_bytes import bytes32

from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_public_key_and_hidden_puzzle_hash

from src.wallet.puzzles.load_clvm import load_clvm

MOD = load_clvm("atomic_swap.clvm")


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
        get_safe_transaction_puzzle_hash(source_pubkey, target_pubkey, claim_height, preimage_hash),
    )


def get_standard_puzzle_hash_with_safe(
    source_pubkey: G1Element, target_pubkey: G1Element, claim_height: int, preimage_hash: bytes32
) -> Program:
    return get_standard_puzzle_with_safe(source_pubkey, target_pubkey, claim_height, preimage_hash).get_tree_hash()


# target == 0 will act as though this is the source attempting to claim it back,
# all other values will require a valid preimage
def generate_safe_solution(
    preimage: bytes32, target: int, delegated_puzzle: Program, delegated_solution: Program
) -> Program:
    return Program.to([preimage, target, delegated_puzzle, delegated_solution])


def get_preimage_from_claim_solution(solution: Program) -> str:
    return solution.as_python()[0].decode("utf-8")
