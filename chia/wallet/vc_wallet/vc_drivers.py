from typing import List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_MOD_HASH, SINGLETON_LAUNCHER_HASH
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

COVENANT_LAYER: Program = load_clvm_maybe_recompile("covenant_layer.clsp")
NFT_TP_COVENANT_ADAPTER: Program = load_clvm_maybe_recompile("nft_transfer_program_covenant_adapter.clsp")
NFT_DID_TP: Program = load_clvm_maybe_recompile("nft_update_metadata_with_DID.clsp")
DID_BACKDOOR: Program = load_clvm_maybe_recompile("did_backdoor.clsp")
P2_PUZZLE_OR_HIDDEN_PUZZLE: Program = load_clvm_maybe_recompile("p2_puzzle_or_hidden_puzzle.clsp")


##################
# Covenant Layer #
##################
def create_covenant_layer(covenants: List[Program], inner_puzzle: Program) -> Program:
    return COVENANT_LAYER.curry(
        covenants,
        inner_puzzle,
    )


def match_covenant_layer(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[List[Program], Program]]:
    if uncurried_puzzle.mod == COVENANT_LAYER:
        return list(uncurried_puzzle.args.at("f").as_iter()), uncurried_puzzle.args.at("rf")
    else:
        return None


def solve_covenant_layer(
    enforce: bool, covenant_solutions: List[Program], lineage_proof: LineageProof, inner_solution: Program
) -> Program:
    solution: Program = Program.to(
        [
            enforce,
            covenant_solutions,
            lineage_proof.to_program(),
            inner_solution,
        ]
    )
    return solution


####################
# Covenant Adapter #
####################
def create_tp_covenant_adapter(covenant_layer: Program) -> Program:
    return NFT_TP_COVENANT_ADAPTER.curry(covenant_layer)


def match_tp_covenant_adapter(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[Program]]:
    if uncurried_puzzle.mod == NFT_TP_COVENANT_ADAPTER:
        return uncurried_puzzle.args.at("f")
    else:
        return None


def solve_tp_covenant_adapter(
    covenant_solutions: List[Program], lineage_proof: LineageProof, inner_solution: Program
) -> Program:
    solution: Program = Program.to(
        [
            covenant_solutions,
            lineage_proof.to_program(),
            inner_solution,
        ]
    )
    return solution


##################################
# Update w/ DID Transfer Program #
##################################
def create_did_tp(
    did_id: bytes32,
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> Program:
    return NFT_DID_TP.curry(
        (singleton_mod_hash, (did_id, singleton_launcher_hash)),
    )


def match_did_tp(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32]]:
    if uncurried_puzzle.mod == NFT_DID_TP:
        return (bytes32(uncurried_puzzle.args.at("frf").as_python()),)
    else:
        return None


def solve_did_tp(
    provider_innerpuzhash: bytes32, my_coin_id: bytes32, new_metadata: Program, new_transfer_program: Program
) -> Program:
    solution: Program = Program.to(
        provider_innerpuzhash,
        my_coin_id,
        new_metadata,
        new_transfer_program,
    )
    return solution


################
# DID Backdoor #
################
def create_did_backdoor(
    did_id: bytes32,
    brick_conditions: List[Program],
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> Program:
    return DID_BACKDOOR.curry(
        (singleton_mod_hash, (did_id, singleton_launcher_hash)),
        brick_conditions,
    )


def match_did_backdoor(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32, Program]]:
    if uncurried_puzzle.mod == DID_BACKDOOR:
        return bytes32(uncurried_puzzle.args.at("frf").as_python()), uncurried_puzzle.args.at("rf")
    else:
        return None


def solve_did_backdoor(did_innerpuzhash: bytes32, my_coin_id: bytes32) -> Program:
    solution: Program = Program.to(
        did_innerpuzhash,
        my_coin_id,
    )
    return solution


##############################
# P2 Puzzle or Hidden Puzzle #
##############################
def create_p2_puz_or_hidden_puz(hidden_puzzle_hash: bytes32, inner_puzzle: Program) -> Program:
    return P2_PUZZLE_OR_HIDDEN_PUZZLE.curry(
        hidden_puzzle_hash,
        inner_puzzle,
    )


def match_p2_puz_or_hidden_puz(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32, Program]]:
    if uncurried_puzzle.mod == P2_PUZZLE_OR_HIDDEN_PUZZLE:
        return bytes32(uncurried_puzzle.args.at("f").as_python()), uncurried_puzzle.args.at("rf")
    else:
        return None


def solve_p2_puz_or_hidden_puz(inner_solution: Program, hidden_puzzle_reveal: Optional[Program] = None) -> Program:
    solution: Program = Program.to(
        hidden_puzzle_reveal,
        inner_solution,
    )
    return solution
