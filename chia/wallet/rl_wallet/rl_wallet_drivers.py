import math

from typing import Tuple, Callable, List, Any

from blspy import G1Element
from clvm_tools.binutils import assemble

from chia.clvm.singletons.singleton_drivers import (
    wrap_no_melt,
    lineage_proof_for_coinsol,
    launch_conditions_and_coinsol,
    puzzle_for_singleton,
    solution_for_singleton,
    adapt_inner_to_singleton,
    singleton_truths_for_coin_spend,
)
from chia.clvm.taproot.merkle_tree import MerkleTree
from chia.clvm.taproot.taproot_drivers import (
    create_taproot_puzzle,
    create_taproot_solution,
)
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64, uint32
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_delegated_puzzle
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.rl_wallet.rl_drivers import (
    create_rl_puzzle,
    create_rl_solution,
)


class NewUserPuzHash(Exception):
    new_puzhash: bytes32

    def __init__(self, puzhash: bytes32):
        self.new_puzhash = puzhash


class NewAdminPuzHash(Exception):
    new_puzhash: bytes32

    def __init__(self, puzhash: bytes32):
        self.new_puzhash = puzhash


class BadRLState(Exception):
    pass


class RLWalletState:
    singleton_launcher_id: bytes32
    current_lineage_proof: LineageProof
    admin_inner_puzzle: Program
    admin_solution_generator: Any
    user_inner_puzzle: Program
    user_solution_generator: Any
    user_rate: Tuple[uint64, uint32]
    user_earnings_cap: uint64
    user_credit: uint64
    user_last_height: uint32

    """
    Things that will not be visible in the singleton creation:
        - user and admin inner puzzles (and technically their solution generators I suppose)
        - user RL settings
    """

    # Just a standard init, manually set everything
    def __init__(self):
        self.singleton_launcher_id = None
        self.current_lineage_proof = None
        self.admin_inner_puzzle = None
        self.admin_solution_generator = None
        self.user_inner_puzzle = None
        self.user_solution_generator = None
        self.user_rate = None
        self.user_earnings_cap = None
        self.user_credit = None
        self.user_last_height = None

    def set_initial_withdrawal_settings(
        self,
        amount_per: uint64,
        block_interval: uint32,
        earnings_cap: uint64,
        initial_credit: uint64,
        start_height: uint32,
    ):
        self.user_rate = (amount_per, block_interval)
        self.user_earnings_cap = earnings_cap
        self.user_credit = initial_credit
        self.user_last_height = start_height

    def set_initial_custody_settings(
        self,
        admin_inner_puzzle: Program,
        admin_solution_generator: Callable,
        user_inner_puzzle: Program,
        user_solution_generator: Callable,
    ):
        self.admin_inner_puzzle = admin_inner_puzzle
        self.admin_solution_generator = admin_solution_generator
        self.user_inner_puzzle = user_inner_puzzle
        self.user_solution_generator = user_solution_generator

    def set_standard_custody_settings(
        self,
        admin_pubkey: G1Element,
        user_pubkey: G1Element,
    ):
        self.admin_inner_puzzle = adapt_inner_to_singleton(puzzle_for_pk(admin_pubkey))
        self.admin_solution_generator = solution_for_delegated_puzzle
        self.user_inner_puzzle = adapt_inner_to_singleton(puzzle_for_pk(user_pubkey))
        self.user_solution_generator = solution_for_delegated_puzzle

    def set_initial_singleton_settings(
        self,
        launcher_coin_spend: CoinSpend,
    ):
        self.singleton_launcher_id = launcher_coin_spend.coin.name()
        self.current_lineage_proof = lineage_proof_for_coinsol(launcher_coin_spend)

    def create_user_rl_puzzle(self) -> Program:
        return create_rl_puzzle(
            self.user_rate[0],
            self.user_rate[1],
            self.user_earnings_cap,
            self.user_credit,
            self.user_last_height,
            self.user_inner_puzzle,
        )

    def create_full_user_innerpuz(self) -> Program:
        return wrap_no_melt(self.create_user_rl_puzzle())

    def get_tree(self) -> MerkleTree:
        return MerkleTree(
            [
                self.create_full_user_innerpuz().get_tree_hash(),
                self.admin_inner_puzzle.get_tree_hash(),
            ]
        )

    def create_taproot_innerpuz(self) -> Program:
        return create_taproot_puzzle(self.get_tree())

    def create_full_puzzle(self) -> Program:
        return puzzle_for_singleton(self.singleton_launcher_id, self.create_taproot_innerpuz())

    def create_launch_spend(self, source_coin: Coin, amount: uint64) -> Tuple[List[Program], CoinSpend]:
        return launch_conditions_and_coinsol(
            source_coin,
            self.create_taproot_innerpuz(),
            [],
            amount,
        )

    def create_user_spend(self, coin: Coin, current_block_height: uint32, *args) -> CoinSpend:
        full_user_innerpuz: Program = self.create_full_user_innerpuz()
        puzzle: Program = self.create_full_puzzle()
        solution: Program = solution_for_singleton(
            self.current_lineage_proof,
            coin.amount,
            create_taproot_solution(
                self.get_tree(),
                full_user_innerpuz,
                Program.to(
                    [  # Extra "parens" because of the no melt puzzle
                        create_rl_solution(
                            uint32(current_block_height),
                            self.user_solution_generator(*args),
                        )
                    ]
                ),
            ),
        )
        return CoinSpend(
            coin,
            puzzle,
            solution,
        )

    def create_admin_spend(self, coin: Coin, *args) -> CoinSpend:
        puzzle: Program = self.create_full_puzzle()
        solution: Program = solution_for_singleton(
            self.current_lineage_proof,
            coin.amount,
            create_taproot_solution(self.get_tree(), self.admin_inner_puzzle, self.admin_solution_generator(*args)),
        )
        return CoinSpend(
            coin,
            puzzle,
            solution,
        )

    def update_state_for_coin_spend(self, coin_spend: CoinSpend):
        total_conditions: List[List] = (
            coin_spend.puzzle_reveal.to_program().run(coin_spend.solution.to_program()).as_python()
        )
        final_singleton_condition: List = next(
            condition
            for condition in total_conditions
            if ((int.from_bytes(condition[0], "big") == 51) and (int.from_bytes(condition[2], "big") % 2 == 1))
        )

        # inner_solution.inner_puzzle
        inner_puzzle_extractor = Program.to(assemble("(f (r (f (r (r 1)))))"))
        revealed_inner_puzzle: Program = inner_puzzle_extractor.run(coin_spend.solution.to_program())
        if revealed_inner_puzzle == self.admin_inner_puzzle:
            try:
                assert self.create_full_puzzle().get_tree_hash() == final_singleton_condition[1]
            except AssertionError:
                try:
                    # inner_solution.inner_solution
                    solution_extractor = Program.to(assemble("(f (r (r (f (r (r 1))))))"))
                    revealed_solution: Program = solution_extractor.run(coin_spend.solution.to_program())
                    truths_appended = Program.to((singleton_truths_for_coin_spend(coin_spend), revealed_solution))
                    conditions: List[List] = self.admin_inner_puzzle.run(truths_appended).as_python()
                    singleton_condition: List = next(
                        condition
                        for condition in conditions
                        if (
                            (int.from_bytes(condition[0], "big") == 51)
                            and (int.from_bytes(condition[2], "big") % 2 == 1)
                        )
                    )
                    assert self.admin_inner_puzzle.get_tree_hash() == singleton_condition[1]
                except AssertionError:
                    raise NewAdminPuzHash(singleton_condition[1])
                raise BadRLState()
        elif revealed_inner_puzzle == self.create_full_user_innerpuz():
            # inner_solution.inner_solution.[current_height, inner_solution]
            rl_solution_extractor = Program.to(assemble("(f (f (r (r (f (r (r 1)))))))"))
            rl_solution: Program = rl_solution_extractor.run(coin_spend.solution.to_program())
            current_height = int.from_bytes(Program.to(assemble("(f 1)")).run(rl_solution).as_python(), "big")
            innermost_solution = Program.to(assemble("(f (r 1))")).run(rl_solution)
            truths_appended = Program.to((singleton_truths_for_coin_spend(coin_spend), innermost_solution))
            conditions = self.user_inner_puzzle.run(truths_appended).as_python()
            singleton_condition = next(
                condition
                for condition in conditions
                if ((int.from_bytes(condition[0], "big") == 51) and (int.from_bytes(condition[2], "big") % 2 == 1))
            )

            cache_credit: uint64 = self.user_credit
            cache_last_height: uint32 = self.user_last_height
            # Calculate just like the Chialisp
            potential_withdrawal: int = min(
                self.user_earnings_cap,
                (math.floor(self.user_rate[0] / self.user_rate[1]) * max(0, (current_height - self.user_last_height)) + self.user_credit),
            )
            actual_withdrawal: int = max(0, coin_spend.coin.amount - int.from_bytes(singleton_condition[2], "big"))
            self.user_credit = uint64(potential_withdrawal - actual_withdrawal)
            self.user_last_height = current_height

            try:
                assert self.create_full_puzzle().get_tree_hash() == final_singleton_condition[1]
            except AssertionError:
                self.user_credit = cache_credit
                self.user_last_height = user_last_height
                try:
                    assert self.user_inner_puzzle.get_tree_hash() == singleton_condition[1]
                except AssertionError:
                    raise NewUserPuzHash(singleton_condition[1])
                raise BadRLState()
        else:
            raise BadRLState()

        self.current_lineage_proof = lineage_proof_for_coinsol(coin_spend)
