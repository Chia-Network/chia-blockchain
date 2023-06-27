from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator, List, Optional, Tuple, Type, TypeVar

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
    generate_launcher_coin,
    puzzle_for_singleton,
    solution_for_singleton,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle

# Mods
EXTIGENT_METADATA_LAYER = load_clvm_maybe_recompile(
    "exigent_metadata_layer.clsp",
    package_or_requirement="chia.wallet.vc_wallet.vc_puzzles",
    include_standard_libraries=True,
)
P2_ANNOUNCED_DELEGATED_PUZZLE: Program = load_clvm_maybe_recompile(
    "p2_announced_delegated_puzzle.clsp",
    package_or_requirement="chia.wallet.vc_wallet.vc_puzzles",
    include_standard_libraries=True,
)
COVENANT_LAYER: Program = load_clvm_maybe_recompile(
    "covenant_layer.clsp", package_or_requirement="chia.wallet.vc_wallet.vc_puzzles", include_standard_libraries=True
)
STD_COVENANT_PARENT_MORPHER: Program = load_clvm_maybe_recompile(
    "std_parent_morpher.clsp",
    package_or_requirement="chia.wallet.vc_wallet.vc_puzzles",
    include_standard_libraries=True,
)
EML_TP_COVENANT_ADAPTER: Program = load_clvm_maybe_recompile(
    "eml_transfer_program_covenant_adapter.clsp",
    package_or_requirement="chia.wallet.vc_wallet.vc_puzzles",
    include_standard_libraries=True,
)
EML_DID_TP: Program = load_clvm_maybe_recompile(
    "eml_update_metadata_with_DID.clsp",
    package_or_requirement="chia.wallet.vc_wallet.vc_puzzles",
    include_standard_libraries=True,
)
EXTIGENT_METADATA_LAYER_COVENANT_MORPHER: Program = load_clvm_maybe_recompile(
    "eml_covenant_morpher.clsp",
    package_or_requirement="chia.wallet.vc_wallet.vc_puzzles",
    include_standard_libraries=True,
)
VIRAL_BACKDOOR: Program = load_clvm_maybe_recompile(
    "viral_backdoor.clsp", package_or_requirement="chia.wallet.vc_wallet.vc_puzzles", include_standard_libraries=True
)
# (mod (METADATA conditions . solution) (if solution solution (list METADATA () ())))
# (a (i 7 (q . 7) (q 4 2 (q () ()))) 1)
ACS_TRANSFER_PROGRAM: Program = Program.to([2, [3, 7, (1, 7), [1, 4, 2, [1, None, None]]], 1])

# Hashes
EXTIGENT_METADATA_LAYER_HASH = EXTIGENT_METADATA_LAYER.get_tree_hash()
P2_ANNOUNCED_DELEGATED_PUZZLE_HASH: bytes32 = P2_ANNOUNCED_DELEGATED_PUZZLE.get_tree_hash()
COVENANT_LAYER_HASH: bytes32 = COVENANT_LAYER.get_tree_hash()
STD_COVENANT_PARENT_MORPHER_HASH: bytes32 = STD_COVENANT_PARENT_MORPHER.get_tree_hash()
EML_TP_COVENANT_ADAPTER_HASH: bytes32 = EML_TP_COVENANT_ADAPTER.get_tree_hash()
EXTIGENT_METADATA_LAYER_COVENANT_MORPHER_HASH: bytes32 = EXTIGENT_METADATA_LAYER_COVENANT_MORPHER.get_tree_hash()
VIRAL_BACKDOOR_HASH: bytes32 = VIRAL_BACKDOOR.get_tree_hash()


# Standard brick puzzle uses the mods above
STANDARD_BRICK_PUZZLE: Program = load_clvm_maybe_recompile(
    "standard_vc_backdoor_puzzle.clsp",
    package_or_requirement="chia.wallet.vc_wallet.vc_puzzles",
    include_standard_libraries=True,
).curry(
    SINGLETON_MOD_HASH,
    Program.to(SINGLETON_LAUNCHER_HASH).get_tree_hash(),
    EXTIGENT_METADATA_LAYER_HASH,
    VIRAL_BACKDOOR_HASH,
    ACS_TRANSFER_PROGRAM.get_tree_hash(),
)
STANDARD_BRICK_PUZZLE_HASH: bytes32 = STANDARD_BRICK_PUZZLE.get_tree_hash()
STANDARD_BRICK_PUZZLE_HASH_HASH: bytes32 = Program.to(STANDARD_BRICK_PUZZLE_HASH).get_tree_hash()


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
            bytes32(uncurried_puzzle.args.at("f").atom),
            uncurried_puzzle.args.at("rf"),
            uncurried_puzzle.args.at("rrf"),
        )
    else:
        return None  # pragma: no cover


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
    """
    The standard PARENT_MORPHER for plain coins that want to prove an initial state
    """
    return STD_COVENANT_PARENT_MORPHER.curry(
        STD_COVENANT_PARENT_MORPHER_HASH,
        COVENANT_LAYER_HASH,
        initial_puzzle_hash,
    )


####################
# Covenant Adapter #
####################
def create_tp_covenant_adapter(covenant_layer: Program) -> Program:
    return EML_TP_COVENANT_ADAPTER.curry(covenant_layer)


def match_tp_covenant_adapter(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[Program]]:  # pragma: no cover
    if uncurried_puzzle.mod == EML_TP_COVENANT_ADAPTER:
        return uncurried_puzzle.args.at("f")
    else:
        return None


##################################
# Update w/ DID Transfer Program #
##################################
def create_did_tp(
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> Program:
    return EML_DID_TP.curry(
        singleton_mod_hash,
        singleton_launcher_hash,
    )


EML_DID_TP_FULL_HASH = create_did_tp().get_tree_hash()


def match_did_tp(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[()]]:
    if uncurried_puzzle.mod == EML_DID_TP:
        return ()
    else:
        return None  # pragma: no cover


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
# P2 Puzzle or Hidden Puzzle #
##############################
def create_viral_backdoor(hidden_puzzle_hash: bytes32, inner_puzzle_hash: bytes32) -> Program:
    return VIRAL_BACKDOOR.curry(
        VIRAL_BACKDOOR_HASH,
        hidden_puzzle_hash,
        inner_puzzle_hash,
    )


def match_viral_backdoor(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32, bytes32]]:
    if uncurried_puzzle.mod == VIRAL_BACKDOOR:
        return bytes32(uncurried_puzzle.args.at("rf").atom), bytes32(uncurried_puzzle.args.at("rrf").atom)
    else:
        return None  # pragma: no cover


def solve_viral_backdoor(puzzle_reveal: Program, inner_solution: Program, hidden: bool = False) -> Program:
    solution: Program = Program.to(
        [
            hidden,
            puzzle_reveal,
            inner_solution,
        ]
    )
    return solution


########
# MISC #
########
def create_eml_covenant_morpher(
    transfer_program_hash: bytes32,
) -> Program:
    """
    A PARENT_MORPHER for use in the covenant layer that proves the parent is a singleton -> EML -> Covenant stack
    """
    first_curry: Program = EXTIGENT_METADATA_LAYER_COVENANT_MORPHER.curry(
        COVENANT_LAYER_HASH,
        EXTIGENT_METADATA_LAYER_HASH,
        EML_TP_COVENANT_ADAPTER_HASH,
        SINGLETON_MOD_HASH,
        Program.to(SINGLETON_LAUNCHER_HASH).get_tree_hash(),
        transfer_program_hash,
    )
    return first_curry.curry(first_curry.get_tree_hash())


def construct_exigent_metadata_layer(
    metadata: Optional[bytes32],
    transfer_program: Program,
    inner_puzzle: Program,
) -> Program:
    return EXTIGENT_METADATA_LAYER.curry(
        EXTIGENT_METADATA_LAYER_HASH,
        metadata,
        transfer_program,
        transfer_program.get_tree_hash(),
        inner_puzzle,
    )


@streamable
@dataclass(frozen=True)
class VCLineageProof(LineageProof, Streamable):
    """
    The covenant layer for exigent metadata layers requires to be passed the previous parent's metadata too
    """

    parent_proof_hash: Optional[bytes32] = None


def solve_std_vc_backdoor(
    launcher_id: bytes32,
    metadata_hash: bytes32,
    tp_hash: bytes32,
    inner_puzzle_hash: bytes32,
    amount: uint64,
    eml_lineage_proof: VCLineageProof,
    provider_innerpuzhash: bytes32,
    coin_id: bytes32,
    announcement_nonce: Optional[bytes32] = None,
) -> Program:
    """
    Solution to the STANDARD_BRICK_PUZZLE above. Requires proof info about pretty much the whole puzzle stack.
    """
    solution: Program = Program.to(
        [
            launcher_id,
            metadata_hash,
            tp_hash,
            STANDARD_BRICK_PUZZLE_HASH_HASH,
            inner_puzzle_hash,
            amount,
            eml_lineage_proof.to_program(),
            Program.to(eml_lineage_proof.parent_proof_hash),
            announcement_nonce,
            Program.to(
                [
                    provider_innerpuzhash,
                    coin_id,
                ]
            ),
        ]
    )
    return solution


# Launching to a VC requires a OL with a transfer program that guarantees a () metadata on the next iteration
# (mod (_ _ (provider tp)) (list (c provider ()) tp ()))
# (c (c 19 ()) (c 43 (q ())))
GUARANTEED_NIL_TP: Program = Program.fromhex("ff04ffff04ff13ff8080ffff04ff2bffff01ff80808080")
OWNERSHIP_LAYER_LAUNCHER: Program = construct_exigent_metadata_layer(
    None,
    GUARANTEED_NIL_TP,
    P2_ANNOUNCED_DELEGATED_PUZZLE,
)
OWNERSHIP_LAYER_LAUNCHER_HASH = OWNERSHIP_LAYER_LAUNCHER.get_tree_hash()


########################
# Verified Credentials #
########################
_T_VerifiedCredential = TypeVar("_T_VerifiedCredential", bound="VerifiedCredential")


@streamable
@dataclass(frozen=True)
class VerifiedCredential(Streamable):
    """
    This class serves as the main driver for the entire VC puzzle stack. Given the information below, it can sync and
    spend VerifiedCredentials in any specified manner. Trying to sync from a spend that this class did not create will
    likely result in an error.
    """

    coin: Coin
    singleton_lineage_proof: LineageProof
    eml_lineage_proof: VCLineageProof
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
        memos: List[bytes32],
        fee: uint64 = uint64(0),
    ) -> Tuple[Program, List[CoinSpend], _T_VerifiedCredential]:
        """
        Launch a VC.

        origin_coin: An XCH coin that will be used to fund the spend. A coin of any amount > 1 can be used and the
        change will automatically go back to the coin's puzzle hash.
        provider_id: The DID of the proof provider (the entity who is responsible for adding/removing proofs to the vc)
        new_inner_puzzle_hash: the innermost puzzle hash once the VC is created
        memos: The memos to use on the payment to the singleton

        Returns a delegated puzzle to run (with any solution), a list of spends to push with the origin transaction,
        and an instance of this class representing the expected state after all relevant spends have been pushed and
        confirmed.
        """
        launcher_coin: Coin = generate_launcher_coin(origin_coin, uint64(1))

        # Create the second puzzle for the first launch
        curried_eve_singleton: Program = puzzle_for_singleton(
            launcher_coin.name(),
            OWNERSHIP_LAYER_LAUNCHER,
        )
        curried_eve_singleton_hash: bytes32 = curried_eve_singleton.get_tree_hash()
        launcher_solution = Program.to([curried_eve_singleton_hash, uint64(1), None])

        # Create the final puzzle for the second launch
        inner_transfer_program: Program = create_did_tp()
        transfer_program: Program = create_tp_covenant_adapter(
            create_covenant_layer(
                curried_eve_singleton_hash,
                create_eml_covenant_morpher(
                    inner_transfer_program.get_tree_hash(),
                ),
                inner_transfer_program,
            )
        )
        wrapped_inner_puzzle_hash: bytes32 = create_viral_backdoor(
            STANDARD_BRICK_PUZZLE_HASH,
            new_inner_puzzle_hash,
        ).get_tree_hash()
        metadata_layer_hash: bytes32 = construct_exigent_metadata_layer(
            Program.to((provider_id, None)),
            transfer_program,
            wrapped_inner_puzzle_hash,  # type: ignore
        ).get_tree_hash_precalc(wrapped_inner_puzzle_hash)
        curried_singleton_hash: bytes32 = puzzle_for_singleton(
            launcher_coin.name(),
            metadata_layer_hash,  # type: ignore
        ).get_tree_hash_precalc(metadata_layer_hash)
        launch_dpuz: Program = Program.to(
            (
                1,
                [
                    [51, wrapped_inner_puzzle_hash, uint64(1), memos],
                    [1, new_inner_puzzle_hash],
                    [-10, provider_id, transfer_program.get_tree_hash()],
                ],
            )
        )
        second_launcher_solution = Program.to([launch_dpuz, None])
        second_launcher_coin: Coin = Coin(
            launcher_coin.name(),
            curried_eve_singleton_hash,
            uint64(1),
        )
        create_launcher_conditions = Program.to(
            [
                [51, SINGLETON_LAUNCHER_HASH, 1],
                [51, origin_coin.puzzle_hash, origin_coin.amount - fee - 1],
                [52, fee],
                [61, std_hash(launcher_coin.name() + launcher_solution.get_tree_hash())],
                [61, std_hash(second_launcher_coin.name() + launch_dpuz.get_tree_hash())],
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

    ####################################################################################################################
    # The methods in this section give insight into the structure of the puzzle stack that is considered a "VC"
    def construct_puzzle(self) -> Program:
        return puzzle_for_singleton(
            self.launcher_id,
            self.construct_exigent_metadata_layer(),
        )

    def construct_exigent_metadata_layer(self) -> Program:
        return construct_exigent_metadata_layer(
            Program.to((self.proof_provider, self.proof_hash)),
            self.construct_transfer_program(),
            self.wrap_inner_with_backdoor(),
        )

    def construct_transfer_program(self) -> Program:
        curried_eve_singleton_hash: bytes32 = puzzle_for_singleton(
            self.launcher_id,
            OWNERSHIP_LAYER_LAUNCHER,
        ).get_tree_hash()
        inner_transfer_program: Program = create_did_tp()

        return create_tp_covenant_adapter(
            create_covenant_layer(
                curried_eve_singleton_hash,
                create_eml_covenant_morpher(
                    inner_transfer_program.get_tree_hash(),
                ),
                inner_transfer_program,
            ),
        )

    def wrap_inner_with_backdoor(self) -> Program:
        return create_viral_backdoor(
            self.hidden_puzzle().get_tree_hash(),
            self.inner_puzzle_hash,
        )

    def hidden_puzzle(self) -> Program:
        return STANDARD_BRICK_PUZZLE

    ####################################################################################################################

    @staticmethod
    def is_vc(puzzle_reveal: UncurriedPuzzle) -> Tuple[bool, str]:
        """
        This takes an (uncurried) puzzle reveal and returns a boolean for whether the puzzle is a VC and an error
        message for if the puzzle is a mismatch. Returns True for VC launcher spends.
        """
        if puzzle_reveal.mod != SINGLETON_MOD:
            return False, "top most layer is not a singleton"
        layer_below_singleton: UncurriedPuzzle = uncurry_puzzle(puzzle_reveal.args.at("rf"))
        if layer_below_singleton.mod != EXTIGENT_METADATA_LAYER:
            return False, "layer below singleton is not an exigent metadata layer"

        # Need to validate both transfer program...
        full_transfer_program_as_prog: Program = layer_below_singleton.args.at("rrf")
        full_transfer_program: UncurriedPuzzle = uncurry_puzzle(full_transfer_program_as_prog)
        if full_transfer_program.mod != EML_TP_COVENANT_ADAPTER:
            # This is the first spot we'll run into trouble if we're examining a VC being launched
            # Break off to that logic here
            if full_transfer_program_as_prog == GUARANTEED_NIL_TP:
                if layer_below_singleton.args.at("rrrrf") != P2_ANNOUNCED_DELEGATED_PUZZLE:
                    return (
                        False,
                        "tp indicates VC is launching, but it does not have the correct inner puzzle",
                    )  # pragma: no cover
                else:
                    return True, ""
            else:
                return False, "top layer of transfer program is not a covenant layer adapter"  # pragma: no cover
        adapted_transfer_program: UncurriedPuzzle = uncurry_puzzle(full_transfer_program.args.at("f"))
        if adapted_transfer_program.mod != COVENANT_LAYER:
            return (
                False,
                "transfer program is adapted to covenant layer, but covenant layer did not follow",
            )  # pragma: no cover
        morpher: UncurriedPuzzle = uncurry_puzzle(adapted_transfer_program.args.at("rf"))
        if uncurry_puzzle(morpher.mod).mod != EXTIGENT_METADATA_LAYER_COVENANT_MORPHER:
            return (
                False,
                "covenant for exigent metadata layer does not match the one expected for VCs",
            )  # pragma: no cover
        if uncurry_puzzle(adapted_transfer_program.args.at("rrf")).mod != EML_DID_TP:
            return (
                False,
                "transfer program for exigent metadata layer was not the standard VC transfer program",
            )  # pragma: no cover

        # ...and layer below EML
        layer_below_eml: UncurriedPuzzle = uncurry_puzzle(layer_below_singleton.args.at("rrrrf"))
        if layer_below_eml.mod != VIRAL_BACKDOOR:
            return False, "VC did not have a provider backdoor"  # pragma: no cover
        hidden_puzzle_hash: bytes32 = layer_below_eml.args.at("rf")
        if hidden_puzzle_hash != STANDARD_BRICK_PUZZLE_HASH:
            return (
                False,
                "VC did not have the standard method to brick in its backdoor hidden puzzle slot",
            )  # pragma: no cover

        return True, ""

    @classmethod
    def get_next_from_coin_spend(cls: Type[_T_VerifiedCredential], parent_spend: CoinSpend) -> _T_VerifiedCredential:
        """
        Given a coin spend, this will return the next VC that was create as an output of that spend. This is the main
        method to use when syncing. If a spend has been identified as having a VC puzzle reveal, running this method
        on that spend should succeed unless the spend in question was the result of a provider using the backdoor to
        revoke the credential.
        """
        coin: Coin = next(c for c in compute_additions(parent_spend) if c.amount % 2 == 1)

        # BEGIN CODE
        parent_coin: Coin = parent_spend.coin
        puzzle: Program = parent_spend.puzzle_reveal.to_program()
        solution: Program = parent_spend.solution.to_program()

        singleton: UncurriedPuzzle = uncurry_puzzle(puzzle)
        launcher_id: bytes32 = bytes32(singleton.args.at("frf").atom)
        layer_below_singleton: Program = singleton.args.at("rf")
        singleton_lineage_proof: LineageProof = LineageProof(
            parent_name=parent_coin.parent_coin_info,
            inner_puzzle_hash=layer_below_singleton.get_tree_hash(),
            amount=uint64(parent_coin.amount),
        )
        if layer_below_singleton == OWNERSHIP_LAYER_LAUNCHER:
            proof_hash: Optional[bytes32] = None
            eml_lineage_proof: VCLineageProof = VCLineageProof(
                parent_name=parent_coin.parent_coin_info, amount=uint64(parent_coin.amount)
            )
            # See what conditions were output by the launcher dpuz and dsol
            dpuz: Program = solution.at("rrf").at("f").at("f")
            dsol: Program = solution.at("rrf").at("f").at("rf")

            conditions: Iterator[Program] = dpuz.run(dsol).as_iter()
            remark_condition: Program = next(c for c in conditions if c.at("f").as_int() == 1)
            inner_puzzle_hash = bytes32(remark_condition.at("rf").atom)
            magic_condition: Program = next(c for c in conditions if c.at("f").as_int() == -10)
            proof_provider = bytes32(magic_condition.at("rf").atom)
        else:
            metadata_layer: UncurriedPuzzle = uncurry_puzzle(layer_below_singleton)

            # Dig to find the inner puzzle / inner solution and extract next inner puzhash and proof hash
            inner_puzzle: Program = solution.at("rrf").at("f").at("rf")
            inner_solution: Program = solution.at("rrf").at("f").at("rrf")
            conditions = inner_puzzle.run(inner_solution).as_iter()
            new_singleton_condition: Program = next(
                c for c in conditions if c.at("f").as_int() == 51 and c.at("rrf").as_int() % 2 != 0
            )
            inner_puzzle_hash = bytes32(new_singleton_condition.at("rf").atom)
            magic_condition = next(c for c in conditions if c.at("f").as_int() == -10)
            if magic_condition.at("rrrf") == Program.to(None):
                proof_hash_as_prog: Program = metadata_layer.args.at("rfr")
            elif magic_condition.at("rrrf").atom is not None:
                raise ValueError("Specified VC was cleared")
            else:
                proof_hash_as_prog = magic_condition.at("rrrfrrf")

            proof_hash = None if proof_hash_as_prog == Program.to(None) else bytes32(proof_hash_as_prog.atom)

            proof_provider = bytes32(metadata_layer.args.at("rff").atom)

            parent_proof_hash: bytes32 = metadata_layer.args.at("rf").get_tree_hash()
            eml_lineage_proof = VCLineageProof(
                parent_name=parent_coin.parent_coin_info,
                inner_puzzle_hash=create_viral_backdoor(
                    STANDARD_BRICK_PUZZLE_HASH,
                    bytes32(uncurry_puzzle(metadata_layer.args.at("rrrrf")).args.at("rrf").atom),
                ).get_tree_hash(),
                amount=uint64(parent_coin.amount),
                parent_proof_hash=None if parent_proof_hash == Program.to(None) else parent_proof_hash,
            )

        new_vc: _T_VerifiedCredential = cls(
            coin,
            singleton_lineage_proof,
            eml_lineage_proof,
            launcher_id,
            inner_puzzle_hash,
            proof_provider,
            proof_hash,
        )
        if new_vc.construct_puzzle().get_tree_hash() != new_vc.coin.puzzle_hash:
            raise ValueError("Error getting new VC from coin spend, probably the child singleton is not a VC")

        return new_vc

    ####################################################################################################################
    # The methods in this section are useful for spending an existing VC
    def magic_condition_for_new_proofs(
        self,
        new_proof_hash: Optional[bytes32],
        provider_innerpuzhash: bytes32,
        new_proof_provider: Optional[bytes32] = None,
    ) -> Program:
        """
        Returns the 'magic' condition that can update the metadata with a new proof hash. Returning this condition from
        the inner puzzle will require a corresponding announcement from the provider DID authorizing that proof hash
        change.
        """
        magic_condition: Program = Program.to(
            [
                -10,
                self.eml_lineage_proof.to_program(),
                [
                    Program.to(self.eml_lineage_proof.parent_proof_hash),
                    self.launcher_id,
                ],
                [
                    provider_innerpuzhash,
                    self.coin.name(),
                    Program.to(new_proof_hash),
                    None,  # TP update is not allowed because then the singleton will leave the VC protocol
                ],
            ]
        )
        return magic_condition

    def standard_magic_condition(self) -> Program:
        """
        Returns the standard magic condition that needs to be returned to the metadata layer. Returning this condition
        from the inner puzzle will leave the proof hash and transfer program the same.
        """
        magic_condition: Program = Program.to(
            [
                -10,
                self.eml_lineage_proof.to_program(),
                [
                    Program.to(self.eml_lineage_proof.parent_proof_hash),
                    self.launcher_id,
                ],
                None,
            ]
        )
        return magic_condition

    def do_spend(
        self,
        inner_puzzle: Program,
        inner_solution: Program,
        new_proof_hash: Optional[bytes32] = None,
        new_proof_provider: Optional[bytes32] = None,
    ) -> Tuple[Optional[bytes32], CoinSpend, "VerifiedCredential"]:
        """
        Given an inner puzzle reveal and solution, spend the VC (potentially updating the proofs in the process).
        Note that the inner puzzle is already expected to output the 'magic' condition (which can be created above).

        Returns potentially the puzzle announcement the spend will expect from the provider DID, the spend of the VC,
        and the expected class representation of the new VC after the spend is pushed and confirmed.
        """
        vc_solution: Program = solution_for_singleton(
            self.singleton_lineage_proof,
            uint64(self.coin.amount),
            Program.to(
                [  # solve EML
                    solve_viral_backdoor(
                        inner_puzzle,
                        inner_solution,
                    ),
                ]
            ),
        )

        if new_proof_hash is not None:
            expected_announcement: Optional[bytes32] = std_hash(
                self.coin.name()
                + Program.to(new_proof_hash).get_tree_hash()
                + b""  # TP update is banned because singleton will leave the VC protocol
            )
        else:
            expected_announcement = None

        new_singleton_condition: Program = next(
            c for c in inner_puzzle.run(inner_solution).as_iter() if c.at("f") == 51 and c.at("rrf").as_int() % 2 != 0
        )
        new_inner_puzzle_hash: bytes32 = bytes32(new_singleton_condition.at("rf").atom)

        return (
            expected_announcement,
            CoinSpend(
                self.coin,
                self.construct_puzzle(),
                vc_solution,
            ),
            self._next_vc(
                new_inner_puzzle_hash,
                self.proof_hash if new_proof_hash is None else new_proof_hash,
                uint64(new_singleton_condition.at("rrf").as_int()),
            ),
        )

    def activate_backdoor(
        self, provider_innerpuzhash: bytes32, announcement_nonce: Optional[bytes32] = None
    ) -> Tuple[bytes32, CoinSpend]:
        """
        Activates the backdoor in the VC to revoke the credentials and remove the provider's DID.

        Returns the announcement we expect from the provider's DID authorizing this, and the spend of the VC.
        Sync attempts by this class on spends generated by this method are expected to fail. This could be improved in
        the future with a separate type/state of VC that is revoked, but perfectly useful as a singleton.
        """
        vc_solution: Program = solution_for_singleton(
            self.singleton_lineage_proof,
            uint64(self.coin.amount),
            Program.to(
                [  # solve EML
                    solve_viral_backdoor(
                        self.hidden_puzzle(),
                        solve_std_vc_backdoor(
                            self.launcher_id,
                            Program.to((self.proof_provider, self.proof_hash)).get_tree_hash(),
                            self.construct_transfer_program().get_tree_hash(),
                            self.inner_puzzle_hash,
                            uint64(self.coin.amount),
                            self.eml_lineage_proof,
                            provider_innerpuzhash,
                            self.coin.name(),
                            announcement_nonce,
                        ),
                        hidden=True,
                    ),
                ]
            ),
        )

        expected_announcement: bytes32 = std_hash(
            self.coin.name() + Program.to(None).get_tree_hash() + ACS_TRANSFER_PROGRAM.get_tree_hash()
        )

        return (
            expected_announcement,
            CoinSpend(self.coin, self.construct_puzzle(), vc_solution),
        )

    ####################################################################################################################

    def _next_vc(
        self, next_inner_puzzle_hash: bytes32, new_proof_hash: Optional[bytes32], next_amount: uint64
    ) -> "VerifiedCredential":
        """
        Private method that creates the next VC class instance.
        """
        slightly_incomplete_vc: VerifiedCredential = VerifiedCredential(
            Coin(self.coin.name(), bytes32([0] * 32), next_amount),
            LineageProof(
                self.coin.parent_coin_info,
                self.construct_exigent_metadata_layer().get_tree_hash(),
                uint64(self.coin.amount),
            ),
            VCLineageProof(
                self.coin.parent_coin_info,
                self.wrap_inner_with_backdoor().get_tree_hash(),
                uint64(self.coin.amount),
                Program.to((self.proof_provider, self.proof_hash)).get_tree_hash(),
            ),
            self.launcher_id,
            next_inner_puzzle_hash,
            self.proof_provider,
            new_proof_hash,
        )

        return replace(
            slightly_incomplete_vc,
            coin=Coin(
                slightly_incomplete_vc.coin.parent_coin_info,
                slightly_incomplete_vc.construct_puzzle().get_tree_hash(),
                slightly_incomplete_vc.coin.amount,
            ),
        )
