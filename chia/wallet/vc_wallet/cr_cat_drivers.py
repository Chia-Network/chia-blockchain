from dataclasses import dataclass, replace
from typing import Iterator, List, Optional, Tuple, Type, TypeVar

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.util.ints import uint64
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_MOD_HASH,
    SINGLETON_LAUNCHER_HASH,
)
from chia.wallet.nft_wallet.nft_puzzles import NFT_OWNERSHIP_LAYER_HASH
from chia.wallet.uncurried_puzzle import UncurriedPuzzle
from chia.wallet.vc_wallet.vc_drivers import (
    NFT_TP_COVENANT_ADAPTER_HASH,
    GUARANTEED_NIL_TP,
    P2_ANNOUNCED_DELEGATED_PUZZLE,
    COVENANT_LAYER_HASH,
    NFT_OWNERSHIP_LAYER_COVENANT_MORPHER_HASH,
    NFT_DID_TP,
)


# Mods
CREDENTIAL_RESTRICTION: Program = load_clvm_maybe_recompile(
    "credential_restriction.clsp",
    package_or_requirement="chia.wallet.vc_wallet.cr_puzzles",
    include_standard_libraries=True,
)
CREDENTIAL_RESTRICTION_HASH: bytes32 = CREDENTIAL_RESTRICTION.get_tree_hash()


# Basic drivers
def construct_cr_layer(
    authorized_providers: List[bytes32],
    proofs_checker: Program,
    inner_puzzle: Program,
) -> Program:
    return CREDENTIAL_RESTRICTION.curry(
        CREDENTIAL_RESTRICTION_HASH,
        Program.to(
            [
                SINGLETON_MOD_HASH,
                SINGLETON_LAUNCHER_HASH,
                NFT_OWNERSHIP_LAYER_HASH,
                NFT_TP_COVENANT_ADAPTER_HASH,
                Program.to(NFT_OWNERSHIP_LAYER_HASH)
                .curry(
                    Program.to(NFT_OWNERSHIP_LAYER_HASH).get_tree_hash(),
                    Program.to(None),
                    GUARANTEED_NIL_TP,
                    P2_ANNOUNCED_DELEGATED_PUZZLE,
                )
                .get_tree_hash_precalc(NFT_OWNERSHIP_LAYER_HASH, Program.to(NFT_OWNERSHIP_LAYER_HASH).get_tree_hash()),
                COVENANT_LAYER_HASH,
                NFT_OWNERSHIP_LAYER_COVENANT_MORPHER_HASH,
                NFT_DID_TP.get_tree_hash(),
            ]
        ),
        authorized_providers,
        proofs_checker,
        inner_puzzle,
    )


def match_cr_layer(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[List[bytes32], Program, Program]]:
    if uncurried_puzzle.mod == CREDENTIAL_RESTRICTION:
        return (
            [bytes32(provider.as_python()) for provider in uncurried_puzzle.args.at("rrf").as_iter()],
            uncurried_puzzle.args.at("rrrf"),
            uncurried_puzzle.args.at("rrrrf"),
        )
    else:
        return None


def solve_cr_layer(
    proof_of_inclusions: Program,
    proof_checker_solution: Program,
    provider_id: bytes32,
    vc_launcher_id: bytes32,
    vc_inner_puzhash: bytes32,
    my_coin_id: bytes32,
    inner_solution: Program,
) -> Program:
    solution: Program = Program.to(
        [
            proof_of_inclusions,
            proof_checker_solution,
            provider_id,
            vc_launcher_id,
            vc_inner_puzhash,
            my_coin_id,
            inner_solution,
        ]
    )
    return solution


_T_CRCAT = TypeVar("_T_CRCAT", bound="CRCAT")


@dataclass(frozen=True)
class CRCAT:
    coin: Coin
    tail_hash: bytes32
    lineage_proof: LineageProof
    authorized_providers: List[bytes32]
    proofs_checker: Program
    inner_puzzle_hash: bytes32

    @classmethod
    def launch(
        cls: Type[_T_CRCAT],
        origin_coin: Coin,
        tail: Program,
        tail_solution: Program,
        authorized_providers: List[bytes32],
        proofs_checker: Program,
        new_inner_puzzle_hash: bytes32,
        hint: bytes32,
    ) -> Tuple[Program, List[CoinSpend], _T_CRCAT]:
        ...

    def construct_puzzle(self) -> Program:
        ...

    @staticmethod
    def is_cr_cat(puzzle_reveal: UncurriedPuzzle) -> Tuple[bool, str]:
        ...

    @classmethod
    def get_next_from_coin_spend(cls: Type[_T_CRCAT], parent_spend: CoinSpend) -> _T_CRCAT:
        ...

    def do_spend(
        self,
        previous_coin_id: bytes32,
        next_coin_proof: LineageProof,
        previous_subtotal: int,
        extra_delta: int,
        inner_puzzle: Program,
        inner_solution: Program,
    ) -> Tuple[List[bytes32], CoinSpend, "CRCAT"]:
        ...

    @classmethod
    def spend_many(
        cls: Type[_T_CRCAT],
        spend_params: List[Tuple[_T_CRCAT, Program, Program]],
    ) -> Tuple[List[bytes32], List[CoinSpend], List[_T_CRCAT]]:
        ...
