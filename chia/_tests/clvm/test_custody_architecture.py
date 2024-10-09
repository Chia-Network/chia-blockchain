from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from typing import List, Literal

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
    MorpherOrValidator,
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
def test_back_and_forth_hint_parsing(restrictions: List[Restriction[MorpherOrValidator]], puzzle: Puzzle) -> None:
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
        def morpher_not_validator(self) -> bool:
            raise NotImplementedError()

        def memo(self, nonce: int) -> Program:
            raise NotImplementedError()

        def puzzle(self, nonce: int) -> Program:
            raise NotImplementedError()

        def puzzle_hash(self, nonce: int) -> bytes32:
            return bytes32([nonce] * 32)

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
            members=[PuzzleWithRestrictions(0, [], unknown_puzzle_0), PuzzleWithRestrictions(1, [], unknown_puzzle_3)],
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
                PuzzleWithRestrictions(1, [], PlaceholderPuzzle()),
            ],
        ),
    )


# (mod (delegated_puzzle . rest) rest)
ACS_MEMBER = Program.to(3)
ACS_MEMBER_PH = ACS_MEMBER.get_tree_hash()


@dataclass(frozen=True)
class ACSMember:
    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        # (r (c (q . nonce) ACS_MEMBER_PH))
        return Program.to([6, [4, (1, nonce), ACS_MEMBER]])

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
async def test_m_of_n(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        for m in range(1, 6):  # 1 - 5 inclusive
            for n in range(1, 6):
                m_of_n = MofN(m, [PuzzleWithRestrictions(n_i, [], ACSMember()) for n_i in range(0, n)])

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
                        ACSMember().puzzle_hash(index): ProvenSpend(
                            ACSMember().puzzle(index),
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


@dataclass(frozen=True)
class ACSPuzzle:
    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return Program.to(1)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class ACSMorpher:
    morpher_not_validator: Literal[True] = field(init=False, default=True)

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        # (mod (conditions . solution) solution)
        return Program.to(3)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class ACSValidator:
    morpher_not_validator: Literal[False] = field(init=False, default=False)

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        # (mod (conditions . program) (a program conditions))
        return Program.to([2, 3, 2])

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
async def test_restriction_layer(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        pwr = PuzzleWithRestrictions(0, [ACSMorpher(), ACSMorpher(), ACSValidator(), ACSValidator()], ACSPuzzle())

        # Farm coin with puzzle inside
        await sim.farm_block(pwr.puzzle_hash())
        pwr_coin = (await client.get_coin_records_by_puzzle_hashes([pwr.puzzle_hash()], include_spent_coins=False))[
            0
        ].coin

        # Some announcements to make a ring between the two morphers and the inner puzzle
        announcement_1 = CreateCoinAnnouncement(msg=b"foo", coin_id=pwr_coin.name())
        announcement_2 = CreateCoinAnnouncement(msg=b"bar", coin_id=pwr_coin.name())
        announcement_3 = CreateCoinAnnouncement(msg=b"qux", coin_id=pwr_coin.name())

        result = await client.push_tx(
            cost_logger.add_cost(
                "Puzzle with 4 restrictions (2 morphers & 2 validators) all ACS",
                WalletSpendBundle(
                    [
                        make_spend(
                            pwr_coin,
                            pwr.puzzle_reveal(),
                            pwr.solve(
                                [
                                    Program.to(
                                        [
                                            announcement_1.to_program(),
                                            announcement_2.corresponding_assertion().to_program(),
                                        ]
                                    ),
                                    Program.to(
                                        [
                                            announcement_2.to_program(),
                                            announcement_3.corresponding_assertion().to_program(),
                                        ]
                                    ),
                                ],
                                [
                                    Program.to(None),
                                    # (mod conditions (r (r (r (r (r (r conditions)))))))
                                    # checks length >= 6
                                    Program.to(127),
                                ],
                                Program.to(
                                    [
                                        announcement_3.to_program(),
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
