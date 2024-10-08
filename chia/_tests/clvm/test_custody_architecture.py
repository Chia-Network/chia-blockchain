from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import List

import pytest
from chia_rs import G2Element

from chia.clvm.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.wallet.conditions import CreateCoinAnnouncement
from chia.wallet.puzzles.custody.custody_architecture import (
    MofN,
    ProvenSpend,
    Puzzle,
    PuzzleHint,
    PuzzleWithRestrictions,
    Restriction,
    RestrictionHint,
    UnknownPuzzle,
    UnknownRestriction,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

BUNCH_OF_ZEROS = bytes32([0] * 32)
BUNCH_OF_ONES = bytes32([1] * 32)
BUNCH_OF_TWOS = bytes32([2] * 32)
BUNCH_OF_THREES = bytes32([3] * 32)
ANY_PROGRAM = Program.to(None)


@pytest.mark.parametrize(
    "restrictions",
    [
        [],
        [UnknownRestriction(RestrictionHint(True, BUNCH_OF_ZEROS, ANY_PROGRAM))],
        [UnknownRestriction(RestrictionHint(False, BUNCH_OF_ZEROS, ANY_PROGRAM))],
        [
            UnknownRestriction(RestrictionHint(True, BUNCH_OF_ZEROS, ANY_PROGRAM)),
            UnknownRestriction(RestrictionHint(False, BUNCH_OF_ZEROS, ANY_PROGRAM)),
        ],
    ],
)
@pytest.mark.parametrize(
    "puzzle",
    [
        UnknownPuzzle(PuzzleHint(BUNCH_OF_ZEROS, ANY_PROGRAM)),
        MofN(
            1,
            [
                PuzzleWithRestrictions(1, [], UnknownPuzzle(PuzzleHint(BUNCH_OF_ZEROS, ANY_PROGRAM))),
                PuzzleWithRestrictions(
                    2,
                    [
                        UnknownRestriction(RestrictionHint(True, BUNCH_OF_ZEROS, ANY_PROGRAM)),
                        UnknownRestriction(RestrictionHint(True, BUNCH_OF_ZEROS, ANY_PROGRAM)),
                    ],
                    UnknownPuzzle(PuzzleHint(BUNCH_OF_ONES, ANY_PROGRAM)),
                ),
            ],
        ),
        MofN(
            2,
            [
                PuzzleWithRestrictions(
                    1,
                    [],
                    MofN(1, [PuzzleWithRestrictions(3, [], UnknownPuzzle(PuzzleHint(BUNCH_OF_ZEROS, ANY_PROGRAM)))]),
                ),
                PuzzleWithRestrictions(
                    4,
                    [],
                    MofN(1, [PuzzleWithRestrictions(5, [], UnknownPuzzle(PuzzleHint(BUNCH_OF_ONES, ANY_PROGRAM)))]),
                ),
            ],
        ),
    ],
)
def test_back_and_forth_hint_parsing(restrictions: List[Restriction], puzzle: Puzzle) -> None:
    cwr = PuzzleWithRestrictions(
        nonce=0,
        restrictions=restrictions,
        puzzle=puzzle,
    )

    assert PuzzleWithRestrictions.from_memo(cwr.memo()) == cwr


def test_unknown_puzzle_behavior() -> None:
    @dataclass(frozen=True)
    class PlaceholderPuzzle:
        @property
        def _morpher_not_validator(self) -> bool:
            raise NotImplementedError()

        def memo(self, nonce: int) -> Program:
            raise NotImplementedError()

        def puzzle(self, nonce: int) -> Program:
            raise NotImplementedError()

        def puzzle_hash(self, nonce: int) -> bytes32:
            raise NotImplementedError()

    # First a simple PuzzleWithRestrictions that is really just a Puzzle
    unknown_puzzle_0 = UnknownPuzzle(PuzzleHint(BUNCH_OF_ZEROS, ANY_PROGRAM))
    pwr = PuzzleWithRestrictions(0, [], unknown_puzzle_0)
    assert pwr.unknown_puzzles == {BUNCH_OF_ZEROS: unknown_puzzle_0}
    known_puzzles = {BUNCH_OF_ZEROS: PlaceholderPuzzle()}
    assert pwr.fill_in_unknown_puzzles(known_puzzles) == PuzzleWithRestrictions(0, [], PlaceholderPuzzle())

    # Now we add some restrictions
    unknown_restriction_1 = UnknownRestriction(RestrictionHint(True, BUNCH_OF_ONES, ANY_PROGRAM))
    unknown_restriction_2 = UnknownRestriction(RestrictionHint(False, BUNCH_OF_TWOS, ANY_PROGRAM))
    pwr = replace(pwr, restrictions=[unknown_restriction_1, unknown_restriction_2])
    assert pwr.unknown_puzzles == {
        BUNCH_OF_ZEROS: unknown_puzzle_0,
        BUNCH_OF_ONES: unknown_restriction_1,
        BUNCH_OF_TWOS: unknown_restriction_2,
    }
    known_puzzles = {
        BUNCH_OF_ZEROS: PlaceholderPuzzle(),
        BUNCH_OF_ONES: PlaceholderPuzzle(),
        BUNCH_OF_TWOS: PlaceholderPuzzle(),
    }
    assert pwr.fill_in_unknown_puzzles(known_puzzles) == PuzzleWithRestrictions(
        0, [PlaceholderPuzzle(), PlaceholderPuzzle()], PlaceholderPuzzle()
    )

    # Now we do test an MofN recursion
    unknown_puzzle_3 = UnknownPuzzle(PuzzleHint(BUNCH_OF_THREES, ANY_PROGRAM))
    pwr = replace(
        pwr,
        puzzle=MofN(
            m=1,
            members=[PuzzleWithRestrictions(0, [], unknown_puzzle_0), PuzzleWithRestrictions(0, [], unknown_puzzle_3)],
        ),
    )
    assert pwr.unknown_puzzles == {
        BUNCH_OF_ZEROS: unknown_puzzle_0,
        BUNCH_OF_ONES: unknown_restriction_1,
        BUNCH_OF_TWOS: unknown_restriction_2,
        BUNCH_OF_THREES: unknown_puzzle_3,
    }
    known_puzzles = {
        BUNCH_OF_ZEROS: PlaceholderPuzzle(),
        BUNCH_OF_ONES: PlaceholderPuzzle(),
        BUNCH_OF_TWOS: PlaceholderPuzzle(),
        BUNCH_OF_THREES: PlaceholderPuzzle(),
    }
    assert pwr.fill_in_unknown_puzzles(known_puzzles) == PuzzleWithRestrictions(
        0,
        [PlaceholderPuzzle(), PlaceholderPuzzle()],
        MofN(
            m=1,
            members=[
                PuzzleWithRestrictions(0, [], PlaceholderPuzzle()),
                PuzzleWithRestrictions(0, [], PlaceholderPuzzle()),
            ],
        ),
    )


# (mod (delegated_puzzle . rest) rest)
ACS = Program.to(3)
ACS_PH = ACS.get_tree_hash()


@dataclass(frozen=True)
class ACSPuzzle:
    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        # (r (c (q . nonce) ACS_PH))
        return Program.to([6, [4, (1, nonce), ACS]])

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
async def test_m_of_n(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        for m in range(1, 6):  # 1 - 5 inclusive
            for n in range(1, 6):
                m_of_n = MofN(m, [PuzzleWithRestrictions(n_i, [], ACSPuzzle()) for n_i in range(0, n)])

                # Farm and find coin
                await sim.farm_block(m_of_n.puzzle_hash(0))
                m_of_n_coin = (
                    await client.get_coin_records_by_puzzle_hashes([m_of_n.puzzle_hash(0)], include_spent_coins=False)
                )[0].coin
                block_height = sim.block_height

                # Create two announcements to be asserted from a) the delegated puzzle b) the puzzle in the MofN
                announcement_1 = CreateCoinAnnouncement(msg=b"foo", coin_id=m_of_n_coin.name())
                announcement_2 = CreateCoinAnnouncement(msg=b"bar", coin_id=m_of_n_coin.name())

                # Test a spend of every combination of m of n
                for indexes in itertools.combinations(range(0, n), m):
                    proven_spends = {
                        ACSPuzzle().puzzle_hash(index): ProvenSpend(
                            ACSPuzzle().puzzle(index),
                            Program.to(
                                [announcement_1.to_program(), announcement_2.corresponding_assertion().to_program()]
                            ),
                        )
                        for index in indexes
                    }
                    proof = m_of_n.merkle_tree.generate_m_of_n_proof(proven_spends)
                    result = await client.push_tx(
                        cost_logger.add_cost(
                            f"M={m}, N={n}, indexes={indexes}",
                            WalletSpendBundle(
                                [
                                    make_spend(
                                        m_of_n_coin,
                                        m_of_n.puzzle(0),
                                        m_of_n.solve(
                                            proof,
                                            Program.to(1),
                                            Program.to(
                                                [
                                                    announcement_2.to_program(),
                                                    announcement_1.corresponding_assertion().to_program(),
                                                ]
                                            ),
                                        ),
                                    )
                                ],
                                G2Element(),
                            ),
                        )
                    )
                    assert result == (MempoolInclusionStatus.SUCCESS, None)
                    await sim.farm_block()
                    await sim.rewind(block_height)
