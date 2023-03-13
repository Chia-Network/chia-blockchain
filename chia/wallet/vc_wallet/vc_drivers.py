from dataclasses import dataclass, replace
from typing import Iterator, List, Optional, Tuple, Type, TypeVar

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.util.ints import uint64
from chia.util.hash import std_hash
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_MOD_HASH,
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    generate_launcher_coin,
    puzzle_for_singleton,
    solution_for_singleton,
)
from chia.wallet.nft_wallet.nft_puzzles import NFT_OWNERSHIP_LAYER_HASH, construct_ownership_layer
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle

COVENANT_LAYER: Program = load_clvm_maybe_recompile("covenant_layer.clsp", package_or_requirement="chia.wallet.puzzles")
COVENANT_LAYER_HASH: bytes32 = COVENANT_LAYER.get_tree_hash()
STD_COVENANT_PARENT_MORPHER: Program = load_clvm_maybe_recompile(
    "std_parent_morpher.clsp", package_or_requirement="chia.wallet.puzzles"
)
STD_COVENANT_PARENT_MORPHER_HASH: bytes32 = STD_COVENANT_PARENT_MORPHER.get_tree_hash()
NFT_TP_COVENANT_ADAPTER: Program = load_clvm_maybe_recompile(
    "nft_transfer_program_covenant_adapter.clsp", package_or_requirement="chia.wallet.puzzles"
)
NFT_TP_COVENANT_ADAPTER_HASH: bytes32 = NFT_TP_COVENANT_ADAPTER.get_tree_hash()
NFT_DID_TP: Program = load_clvm_maybe_recompile(
    "nft_update_metadata_with_DID.clsp", package_or_requirement="chia.wallet.puzzles"
)
NFT_OWNERSHIP_LAYER_COVENANT_MORPHER: Program = load_clvm_maybe_recompile(
    "ownership_layer_covenant_morpher.clsp", package_or_requirement="chia.wallet.puzzles"
)
NFT_OWNERSHIP_LAYER_COVENANT_MORPHER_HASH: bytes32 = NFT_OWNERSHIP_LAYER_COVENANT_MORPHER.get_tree_hash()
EMPTY_METADATA_LAUNCHER_ENFORCER: Program = load_clvm_maybe_recompile(
    "empty_metadata_launcher_enforcer.clsp", package_or_requirement="chia.wallet.puzzles"
)
P2_PUZZLE_WITH_AUTH: Program = load_clvm_maybe_recompile(
    "p2_puzzle_w_auth.clsp", package_or_requirement="chia.wallet.puzzles"
)
DID_PUZZLE_AUTHORIZER: Program = load_clvm_maybe_recompile(
    "did_puzzle_authorizer.clsp", package_or_requirement="chia.wallet.puzzles"
)
VIRAL_BACKDOOR: Program = load_clvm_maybe_recompile("viral_backdoor.clsp", package_or_requirement="chia.wallet.puzzles")
VIRAL_BACKDOOR_HASH: bytes32 = VIRAL_BACKDOOR.get_tree_hash()


##################
# Covenant Layer #
##################
def create_covenant_layer(initial_puzzle_hash: bytes32, parent_morpher: Program, inner_puzzle: Program) -> Program:
    return COVENANT_LAYER.curry(
        initial_puzzle_hash,
        parent_morpher,
        inner_puzzle,
    )


def match_covenant_layer(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32, Program, Program]]:
    if uncurried_puzzle.mod == COVENANT_LAYER:
        return (
            bytes32(uncurried_puzzle.args.at("f").as_python()),
            uncurried_puzzle.args.at("rf"),
            uncurried_puzzle.args.at("rrf"),
        )
    else:
        return None


def solve_covenant_layer(lineage_proof: LineageProof, morpher_solution: Program, inner_solution: Program) -> Program:
    solution: Program = Program.to(
        [
            lineage_proof.to_program(),
            morpher_solution,
            inner_solution,
        ]
    )
    return solution


def create_std_parent_morpher(initial_puzzle_hash: bytes32) -> Program:
    return STD_COVENANT_PARENT_MORPHER.curry(
        STD_COVENANT_PARENT_MORPHER_HASH,
        COVENANT_LAYER_HASH,
        initial_puzzle_hash,
    )


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
        [
            provider_innerpuzhash,
            my_coin_id,
            new_metadata,
            new_transfer_program,
        ]
    )
    return solution


##############################
# P2 Puzzle w/ Authorization #
##############################
def create_p2_puzzle_w_auth(
    auth_func: Program,
    delegated_puzzle: Program,
) -> Program:
    return P2_PUZZLE_WITH_AUTH.curry(
        auth_func,
        delegated_puzzle,
    )


def match_p2_puzzle_w_auth(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[Program, Program]]:
    if uncurried_puzzle.mod == P2_PUZZLE_WITH_AUTH:
        return uncurried_puzzle.args.at("f"), uncurried_puzzle.args.at("rf")
    else:
        return None


def solve_p2_puzzle_w_auth(authorizer_solution: Program, delegated_puzzle_solution: Program) -> Program:
    solution: Program = Program.to(
        [
            authorizer_solution,
            delegated_puzzle_solution,
        ]
    )
    return solution


def create_did_puzzle_authorizer(
    did_id: bytes32,
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> Program:
    return DID_PUZZLE_AUTHORIZER.curry(
        (singleton_mod_hash, (did_id, singleton_launcher_hash)),
    )


def match_did_puzzle_authorizer(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32]]:
    if uncurried_puzzle.mod == DID_PUZZLE_AUTHORIZER:
        return (bytes32(uncurried_puzzle.args.at("frf").as_python()),)
    else:
        return None


def solve_did_puzzle_authorizer(did_innerpuzhash: bytes32, my_coin_id: bytes32) -> Program:
    solution: Program = Program.to(
        [
            did_innerpuzhash,
            my_coin_id,
        ]
    )
    return solution


##############################
# P2 Puzzle or Hidden Puzzle #
##############################
def create_viral_backdoor(hidden_puzzle_hash: bytes32, inner_puzzle: Program) -> Program:
    return VIRAL_BACKDOOR.curry(
        VIRAL_BACKDOOR_HASH,
        hidden_puzzle_hash,
        inner_puzzle,
    )


def match_viral_backdoor(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32, Program]]:
    if uncurried_puzzle.mod == VIRAL_BACKDOOR:
        return bytes32(uncurried_puzzle.args.at("rf").as_python()), uncurried_puzzle.args.at("rrf")
    else:
        return None


def solve_viral_backdoor(inner_solution: Program, hidden_puzzle_reveal: Optional[Program] = None) -> Program:
    solution: Program = Program.to(
        [
            hidden_puzzle_reveal,
            inner_solution,
        ]
    )
    return solution


########
# MISC #
########
def create_ownership_layer_covenant_morpher(
    covenant_initial_puzzle_hash: bytes32,
    singleton_id: bytes32,
    transfer_program_hash: bytes32,
) -> Program:
    first_curry: Program = NFT_OWNERSHIP_LAYER_COVENANT_MORPHER.curry(
        NFT_OWNERSHIP_LAYER_COVENANT_MORPHER_HASH,
        COVENANT_LAYER_HASH,
        NFT_OWNERSHIP_LAYER_HASH,
        NFT_TP_COVENANT_ADAPTER_HASH,
        Program.to(covenant_initial_puzzle_hash).get_tree_hash(),
        Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH))),
        transfer_program_hash,
    )
    return first_curry.curry(first_curry.get_tree_hash())


OWNERSHIP_LAYER_LAUNCHER: Program = EMPTY_METADATA_LAUNCHER_ENFORCER.curry(
    NFT_OWNERSHIP_LAYER_HASH,
    Program.to(NFT_OWNERSHIP_LAYER_HASH).get_tree_hash(),
    SINGLETON_LAUNCHER,
)
OWNERSHIP_LAYER_LAUNCHER_HASH = OWNERSHIP_LAYER_LAUNCHER.get_tree_hash()


# TODO: Examine whether or not this is an appropiate brick puzzle
STANDARD_BRICK_PUZZLE: Program = Program.to((1, [[51, bytes32([0] * 32), 1], [-10, None]]))


########################
# Verified Credentials #
########################
@dataclass(frozen=True)
class VCLineageProof(LineageProof):
    parent_proof_hash: Optional[bytes32] = None


_T_VerifiedCredential = TypeVar("_T_VerifiedCredential", bound="VerifiedCredential")


@dataclass(frozen=True)
class VerifiedCredential:
    coin: Coin
    singleton_lineage_proof: LineageProof
    ownership_lineage_proof: VCLineageProof
    launcher_id: bytes32
    inner_puzzle_hash: bytes32
    proof_provider: bytes32
    proof_hash: Optional[bytes32]

    @classmethod
    def launch(
        cls: Type[_T_VerifiedCredential],
        origin_coin: Coin,
        provider_id: bytes32,
        new_inner_puzzle_hash: bytes32,
        hint: bytes32,
    ) -> Tuple[Program, List[CoinSpend], _T_VerifiedCredential]:
        launcher_coin: Coin = generate_launcher_coin(origin_coin, uint64(1))

        # Create the second puzzle for the first launch
        curried_eve_singleton: Program = puzzle_for_singleton(
            launcher_coin.name(),
            OWNERSHIP_LAYER_LAUNCHER,
        )
        curried_eve_singleton_hash: bytes32 = curried_eve_singleton.get_tree_hash()
        launcher_solution = Program.to([curried_eve_singleton_hash, uint64(1), None])

        # Create the final puzzle for the second launch
        inner_transfer_program: Program = create_did_tp(provider_id)
        transfer_program: Program = create_tp_covenant_adapter(
            create_covenant_layer(
                curried_eve_singleton_hash,
                create_ownership_layer_covenant_morpher(
                    curried_eve_singleton_hash,
                    launcher_coin.name(),
                    inner_transfer_program.get_tree_hash(),
                ),
                inner_transfer_program,
            )
        )
        wrapped_inner_puzzle_hash: bytes32 = create_viral_backdoor(
            create_p2_puzzle_w_auth(
                create_did_puzzle_authorizer(provider_id),
                STANDARD_BRICK_PUZZLE,
            ).get_tree_hash(),
            new_inner_puzzle_hash,  # type: ignore
        ).get_tree_hash_precalc(new_inner_puzzle_hash)
        ownership_layer_hash: bytes32 = construct_ownership_layer(
            None,
            transfer_program,
            wrapped_inner_puzzle_hash,  # type: ignore
        ).get_tree_hash_precalc(wrapped_inner_puzzle_hash)
        curried_singleton_hash: Program = puzzle_for_singleton(
            launcher_coin.name(),
            ownership_layer_hash,  # type: ignore
        ).get_tree_hash_precalc(ownership_layer_hash)
        second_launcher_solution = Program.to(
            [ownership_layer_hash, uint64(1), [hint, new_inner_puzzle_hash, provider_id]]
        )
        second_launcher_coin: Coin = Coin(
            launcher_coin.name(),
            curried_eve_singleton_hash,
            uint64(1),
        )

        create_launcher_conditions = Program.to(
            [
                [51, SINGLETON_LAUNCHER_HASH, 1],
                [51, origin_coin.puzzle_hash, origin_coin.amount - 1],
                [61, std_hash(launcher_coin.name() + launcher_solution.get_tree_hash())],
                [61, std_hash(second_launcher_coin.name() + second_launcher_solution.get_tree_hash())],
            ]
        )

        dpuz: Program = Program.to((1, create_launcher_conditions))
        return (
            dpuz,
            [
                CoinSpend(
                    launcher_coin,
                    SINGLETON_LAUNCHER,
                    launcher_solution,
                ),
                CoinSpend(
                    second_launcher_coin,
                    curried_eve_singleton,
                    solution_for_singleton(
                        LineageProof(parent_name=launcher_coin.parent_coin_info, amount=uint64(1)),
                        uint64(1),
                        Program.to(
                            [
                                transfer_program.get_tree_hash(),
                                wrapped_inner_puzzle_hash,
                                second_launcher_solution,
                            ]
                        ),
                    ),
                ),
            ],
            cls(
                Coin(second_launcher_coin.name(), curried_singleton_hash, uint64(1)),
                LineageProof(
                    parent_name=second_launcher_coin.parent_coin_info,
                    inner_puzzle_hash=OWNERSHIP_LAYER_LAUNCHER.get_tree_hash(),
                    amount=uint64(1),
                ),
                VCLineageProof(parent_name=second_launcher_coin.parent_coin_info, amount=uint64(1)),
                launcher_coin.name(),
                new_inner_puzzle_hash,
                provider_id,
                None,
            ),
        )

    def construct_puzzle(self, inner_puzzle: Program) -> Program:
        return puzzle_for_singleton(
            self.launcher_id,
            self.construct_ownership_layer(inner_puzzle),
        )

    def construct_ownership_layer(self, inner_puzzle: Program) -> Program:
        curried_eve_singleton_hash: bytes32 = puzzle_for_singleton(
            self.launcher_id,
            OWNERSHIP_LAYER_LAUNCHER,
        ).get_tree_hash()
        inner_transfer_program: Program = create_did_tp(self.proof_provider)

        return construct_ownership_layer(
            self.proof_hash,
            create_tp_covenant_adapter(
                create_covenant_layer(
                    curried_eve_singleton_hash,
                    create_ownership_layer_covenant_morpher(
                        curried_eve_singleton_hash,
                        self.launcher_id,
                        inner_transfer_program.get_tree_hash(),
                    ),
                    inner_transfer_program,
                ),
            ),
            self.wrap_inner_with_backdoor(inner_puzzle),
        )

    def wrap_inner_with_backdoor(self, inner_puzzle: Program) -> Program:
        return create_viral_backdoor(
            create_p2_puzzle_w_auth(
                create_did_puzzle_authorizer(self.proof_provider),
                STANDARD_BRICK_PUZZLE,
            ).get_tree_hash(),
            inner_puzzle,
        )

    @classmethod
    def get_next_from_coin_spend(cls: Type[_T_VerifiedCredential], parent_spend: CoinSpend) -> _T_VerifiedCredential:
        coin: Coin = next(c for c in compute_additions(parent_spend) if c.amount % 2 == 1)

        # BEGIN CODE
        parent_coin: Coin = parent_spend.coin
        puzzle: Program = parent_spend.puzzle_reveal.to_program()
        solution: Program = parent_spend.solution.to_program()

        singleton: UncurriedPuzzle = uncurry_puzzle(puzzle)
        launcher_id: bytes32 = bytes32(singleton.args.at("frf").as_python())
        layer_below_singleton: Program = singleton.args.at("rf")
        singleton_lineage_proof: LineageProof = LineageProof(
            parent_name=parent_coin.parent_coin_info,
            inner_puzzle_hash=layer_below_singleton.get_tree_hash(),
            amount=uint64(parent_coin.amount),
        )
        if layer_below_singleton == OWNERSHIP_LAYER_LAUNCHER:
            proof_hash: Optional[bytes32] = None
            ownership_lineage_proof: VCLineageProof = VCLineageProof(
                parent_name=parent_coin.parent_coin_info, amount=uint64(parent_coin.amount)
            )
            # Launcher solution makes next coin and hints (to provider)
            launcher_solution_hints: Program = solution.at("rrf").at("rrf").at("rrf")
            inner_puzzle_hash: bytes32 = bytes32(launcher_solution_hints.at("rf").as_python())
            proof_provider: bytes32 = bytes32(launcher_solution_hints.at("rrf").as_python())
        else:
            ownership_layer: UncurriedPuzzle = uncurry_puzzle(layer_below_singleton)

            # Dig to find the inner puzzle / inner solution and extract next inner puzhash and proof hash
            inner_puzzle: Program = uncurry_puzzle(ownership_layer.args.at("rrrf")).args.at("rrf")
            inner_solution: Program = solution.at("rrf").at("f").at("rf")
            conditions: Iterator[Program] = inner_puzzle.run(inner_solution).as_iter()
            new_singleton_condition: Program = next(
                c for c in conditions if c.at("f").as_int() == 51 and c.at("rrf").as_int() % 2 != 0
            )
            inner_puzzle_hash = bytes32(new_singleton_condition.at("rf").as_python())
            magic_condition: Program = next(c for c in conditions if c.at("f").as_int() == -10)
            proof_hash = bytes32(magic_condition.at("rrrfrrf").as_python())

            # Dig to transfer program to get proof provider
            proof_provider = bytes32(
                uncurry_puzzle(
                    uncurry_puzzle(uncurry_puzzle(ownership_layer.args.at("rrf")).args.at("f")).args.at("rrf")
                )
                .args.at("frf")
                .as_python()
            )

            parent_proof_hash: Program = ownership_layer.args.at("rf")
            ownership_lineage_proof = VCLineageProof(
                parent_name=parent_coin.parent_coin_info,
                inner_puzzle_hash=create_viral_backdoor(
                    create_p2_puzzle_w_auth(
                        create_did_puzzle_authorizer(proof_provider),
                        STANDARD_BRICK_PUZZLE,
                    ).get_tree_hash(),
                    inner_puzzle_hash,  # type: ignore
                ).get_tree_hash_precalc(inner_puzzle_hash),
                amount=uint64(parent_coin.amount),
                parent_proof_hash=None
                if parent_proof_hash == Program.to(None)
                else bytes32(parent_proof_hash.as_python()),
            )

        return cls(
            coin,
            singleton_lineage_proof,
            ownership_lineage_proof,
            launcher_id,
            inner_puzzle_hash,
            proof_provider,
            proof_hash,
        )

    def magic_condition_for_new_proofs(
        self,
        new_proof_hash: Optional[bytes32],
        provider_innerpuzhash: bytes32,
    ) -> Program:
        magic_condition: Program = Program.to(
            [
                -10,
                self.ownership_lineage_proof.to_program(),
                [self.ownership_lineage_proof.parent_proof_hash],
                [
                    provider_innerpuzhash,
                    self.coin.name(),
                    new_proof_hash,
                    None,  # TP update is not allowed because then the singleton will leave the VC protocol
                ],
            ]
        )
        return magic_condition

    def update_proofs(
        self,
        new_proof_hash: Optional[bytes32],
        inner_puzzle: Program,
        inner_solution: Program,
    ) -> Tuple[bytes32, CoinSpend, "VerifiedCredential"]:
        vc_solution: Program = solution_for_singleton(
            self.singleton_lineage_proof,
            uint64(self.coin.amount),
            Program.to(
                [  # solve ownership layer
                    solve_viral_backdoor(
                        inner_solution,
                    ),
                ]
            ),
        )

        expected_announcement: bytes32 = std_hash(
            self.coin.name()
            + Program.to(new_proof_hash).get_tree_hash()
            + Program.to(None).get_tree_hash()  # TP update is banned because singleton will leave the VC protocol
        )

        new_singleton_condition: Program = next(
            c for c in inner_puzzle.run(inner_solution).as_iter() if c.at("f") == 51 and c.at("rrf").as_int() % 2 != 0
        )
        new_inner_puzzle_hash: bytes32 = bytes32(new_singleton_condition.at("rf").as_python())

        slightly_incomplete_vc: VerifiedCredential = VerifiedCredential(
            Coin(self.coin.name(), bytes32([0] * 32), uint64(new_singleton_condition.at("rrf").as_int())),
            LineageProof(
                self.coin.parent_coin_info,
                self.construct_ownership_layer(self.inner_puzzle_hash).get_tree_hash_precalc(  # type: ignore
                    self.inner_puzzle_hash
                ),
                uint64(self.coin.amount),
            ),
            VCLineageProof(
                self.coin.parent_coin_info,
                self.wrap_inner_with_backdoor(self.inner_puzzle_hash).get_tree_hash_precalc(  # type: ignore
                    self.inner_puzzle_hash
                ),
                uint64(self.coin.amount),
                self.proof_hash,
            ),
            self.launcher_id,
            new_inner_puzzle_hash,
            self.proof_provider,
            new_proof_hash,
        )

        return (
            expected_announcement,
            CoinSpend(
                self.coin,
                self.construct_puzzle(inner_puzzle),
                vc_solution,
            ),
            replace(
                slightly_incomplete_vc,
                coin=Coin(
                    slightly_incomplete_vc.coin.parent_coin_info,
                    slightly_incomplete_vc.construct_puzzle(
                        new_inner_puzzle_hash  # type: ignore
                    ).get_tree_hash_precalc(new_inner_puzzle_hash),
                    slightly_incomplete_vc.coin.amount,
                ),
            ),
        )
