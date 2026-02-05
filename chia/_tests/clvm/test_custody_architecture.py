from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field, replace
from typing import Literal

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.wallet.conditions import CreateCoinAnnouncement
from chia.wallet.puzzles.custody.custody_architecture import (
    DelegatedPuzzleAndSolution,
    MemberHint,
    MemberOrDPuz,
    MIPSComponent,
    MofN,
    ProvenSpend,
    PuzzleWithRestrictions,
    Restriction,
    RestrictionHint,
    UnknownMember,
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
        # no restrictions
        [],
        # member validator
        [UnknownRestriction(RestrictionHint(member_not_dpuz=True, puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM))],
        # dpuz validator
        [UnknownRestriction(RestrictionHint(member_not_dpuz=False, puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM))],
        # multiple restrictions of various types
        [
            UnknownRestriction(RestrictionHint(member_not_dpuz=True, puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM)),
            UnknownRestriction(RestrictionHint(member_not_dpuz=False, puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM)),
        ],
    ],
)
@pytest.mark.parametrize(
    "puzzle",
    [
        # Custody puzzle
        UnknownMember(MemberHint(puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM)),
        # 1 of 2 (w/ & w/o restrictions)
        MofN(
            m=1,
            members=[
                PuzzleWithRestrictions(
                    nonce=1, restrictions=[], puzzle=UnknownMember(MemberHint(puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM))
                ),
                PuzzleWithRestrictions(
                    nonce=2,
                    restrictions=[
                        UnknownRestriction(
                            RestrictionHint(member_not_dpuz=True, puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM)
                        ),
                        UnknownRestriction(
                            RestrictionHint(member_not_dpuz=True, puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM)
                        ),
                    ],
                    puzzle=UnknownMember(MemberHint(puzhash=BUNCH_OF_ONES, memo=ANY_PROGRAM)),
                ),
            ],
        ),
        # 2 of 2 (further 1 of 1s)
        MofN(
            m=2,
            members=[
                PuzzleWithRestrictions(
                    nonce=1,
                    restrictions=[],
                    puzzle=MofN(
                        m=1,
                        members=[
                            PuzzleWithRestrictions(
                                nonce=3,
                                restrictions=[],
                                puzzle=UnknownMember(MemberHint(puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM)),
                            )
                        ],
                    ),
                ),
                PuzzleWithRestrictions(
                    nonce=4,
                    restrictions=[],
                    puzzle=MofN(
                        m=1,
                        members=[
                            PuzzleWithRestrictions(
                                nonce=5,
                                restrictions=[],
                                puzzle=UnknownMember(MemberHint(puzhash=BUNCH_OF_ONES, memo=ANY_PROGRAM)),
                            )
                        ],
                    ),
                ),
            ],
        ),
    ],
)
def test_back_and_forth_hint_parsing(restrictions: list[Restriction[MemberOrDPuz]], puzzle: MIPSComponent) -> None:
    """
    This tests that a PuzzleWithRestrictions can be exported to a clvm program to be reimported from.

    This is necessary functionality to sync an unknown inner puzzle from on chain.
    """
    cwr = PuzzleWithRestrictions(
        nonce=0,
        restrictions=restrictions,
        puzzle=puzzle,
    )

    assert PuzzleWithRestrictions.from_memo(cwr.memo()) == cwr


def test_unknown_puzzle_behavior() -> None:
    """
    Once an inner puzzle is loaded from chain, all of its nodes are of the UnknownPuzzle type. To spend the puzzle,
    at least one of these nodes must be replaced with a Puzzle that implements the `.puzzle(nonce: int)` method.

    This test tests the ability to replace one or many of these nodes.
    """

    @dataclass(frozen=True)
    class PlaceholderPuzzle:
        @property
        def member_not_dpuz(self) -> bool:
            raise NotImplementedError  # pragma: no cover

        def memo(self, nonce: int) -> Program:
            raise NotImplementedError  # pragma: no cover

        def puzzle(self, nonce: int) -> Program:
            raise NotImplementedError  # pragma: no cover

        def puzzle_hash(self, nonce: int) -> bytes32:
            return bytes32([nonce] * 32)

    # First a simple PuzzleWithRestrictions that is really just a Puzzle
    unknown_puzzle_0 = UnknownMember(MemberHint(puzhash=BUNCH_OF_ZEROS, memo=ANY_PROGRAM))
    pwr = PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=unknown_puzzle_0)
    assert pwr.unknown_puzzles == {BUNCH_OF_ZEROS: unknown_puzzle_0}
    known_puzzles = {BUNCH_OF_ZEROS: PlaceholderPuzzle()}
    assert pwr.fill_in_unknown_puzzles(known_puzzles) == PuzzleWithRestrictions(
        nonce=0, restrictions=[], puzzle=PlaceholderPuzzle()
    )

    # Now we add some restrictions
    unknown_restriction_1 = UnknownRestriction(
        RestrictionHint(member_not_dpuz=True, puzhash=BUNCH_OF_ONES, memo=ANY_PROGRAM)
    )
    unknown_restriction_2 = UnknownRestriction(
        RestrictionHint(member_not_dpuz=False, puzhash=BUNCH_OF_TWOS, memo=ANY_PROGRAM)
    )
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
        nonce=0, restrictions=[PlaceholderPuzzle(), PlaceholderPuzzle()], puzzle=PlaceholderPuzzle()
    )

    # Now we do test an MofN recursion
    unknown_puzzle_3 = UnknownMember(MemberHint(puzhash=BUNCH_OF_THREES, memo=ANY_PROGRAM))
    pwr = replace(
        pwr,
        puzzle=MofN(
            m=1,
            members=[
                PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=unknown_puzzle_0),
                PuzzleWithRestrictions(nonce=1, restrictions=[], puzzle=unknown_puzzle_3),
            ],
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
    filled_in_partial = pwr.fill_in_unknown_puzzles(
        {BUNCH_OF_ZEROS: PlaceholderPuzzle(), BUNCH_OF_ONES: PlaceholderPuzzle()}
    )
    filled_in = filled_in_partial.fill_in_unknown_puzzles(
        {BUNCH_OF_TWOS: PlaceholderPuzzle(), BUNCH_OF_THREES: PlaceholderPuzzle()}
    )
    assert filled_in == PuzzleWithRestrictions(
        nonce=0,
        restrictions=[PlaceholderPuzzle(), PlaceholderPuzzle()],
        puzzle=MofN(
            m=1,
            members=[
                PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=PlaceholderPuzzle()),
                PuzzleWithRestrictions(nonce=1, restrictions=[], puzzle=PlaceholderPuzzle()),
            ],
        ),
    )
    assert filled_in.unknown_puzzles == {}


# (mod (delegated_puzzle . rest) rest)
ACS_MEMBER = Program.to(3)
ACS_MEMBER_PH = ACS_MEMBER.get_tree_hash()


@dataclass(frozen=True)
class ACSMember:
    def memo(self, nonce: int) -> Program:
        raise NotImplementedError  # pragma: no cover

    def puzzle(self, nonce: int) -> Program:
        # (r (c (q . nonce) ACS_MEMBER_PH))
        return Program.to([6, [4, (1, nonce), ACS_MEMBER]])

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class ACSDPuzValidator:
    member_not_dpuz: Literal[False] = field(init=False, default=False)

    def memo(self, nonce: int) -> Program:
        raise NotImplementedError  # pragma: no cover

    def puzzle(self, nonce: int) -> Program:
        # (mod (dpuz . program) (a program conditions))
        return Program.to([2, 3, 2])

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "with_restrictions",
    [True, False],
)
async def test_m_of_n(cost_logger: CostLogger, with_restrictions: bool) -> None:
    """
    This tests the various functionality of the MofN drivers including that m of n puzzles can be constructed and solved
    for every combination of its nodes from size 1 - 5.
    """
    restrictions: list[Restriction[MemberOrDPuz]] = [ACSDPuzValidator()] if with_restrictions else []
    # TODO: This override is necessary because of this limitation
    # https://github.com/Chia-Network/chia-blockchain/blob/67d617d19e5561dd573d0a6e6014db38733c66e2/chia/full_node/mempool_manager.py#L477
    # If that doesn't exist anymore in its current form, we can remove this override.
    async with sim_and_client(defaults=DEFAULT_CONSTANTS.replace(MAX_BLOCK_COST_CLVM=uint64(5_000_000_000))) as (
        sim,
        client,
    ):
        for m in range(1, 6):  # 1 - 5 inclusive
            for n in range(m, 6):
                m_of_n = PuzzleWithRestrictions(
                    nonce=0,
                    restrictions=[],
                    puzzle=MofN(
                        m=m,
                        members=[
                            PuzzleWithRestrictions(nonce=n_i, restrictions=restrictions, puzzle=ACSMember())
                            for n_i in range(n)
                        ],
                    ),
                )

                # Farm and find coin
                await sim.farm_block(m_of_n.puzzle_hash())
                m_of_n_coin = (
                    await client.get_coin_records_by_puzzle_hashes([m_of_n.puzzle_hash()], include_spent_coins=False)
                )[0].coin
                block_height = sim.block_height

                # Create two announcements to be asserted from a) the delegated puzzle b) the puzzle in the MofN
                announcement_1 = CreateCoinAnnouncement(msg=b"foo", coin_id=m_of_n_coin.name())
                announcement_2 = CreateCoinAnnouncement(msg=b"bar", coin_id=m_of_n_coin.name())

                # Test a spend of every combination of m of n
                for indexes in itertools.combinations(range(n), m):
                    proven_spends = {
                        PuzzleWithRestrictions(nonce=index, restrictions=restrictions, puzzle=ACSMember()).puzzle_hash(
                            _top_level=False
                        ): ProvenSpend(
                            puzzle_reveal=PuzzleWithRestrictions(
                                nonce=index, restrictions=restrictions, puzzle=ACSMember()
                            ).puzzle_reveal(_top_level=False),
                            solution=PuzzleWithRestrictions(
                                nonce=index, restrictions=restrictions, puzzle=ACSMember()
                            ).solve(
                                [],
                                [Program.to(None)] if with_restrictions else [],
                                Program.to(
                                    [announcement_1.to_program(), announcement_2.corresponding_assertion().to_program()]
                                ),
                            ),
                        )
                        for index in indexes
                    }
                    assert isinstance(m_of_n.puzzle, MofN)
                    result = await client.push_tx(
                        cost_logger.add_cost(
                            f"M={m}, N={n}, indexes={indexes}{'w/ res.' if with_restrictions else ''}",
                            WalletSpendBundle(
                                [
                                    make_spend(
                                        m_of_n_coin,
                                        m_of_n.puzzle_reveal(),
                                        m_of_n.solve(
                                            [],
                                            [],
                                            m_of_n.puzzle.solve(proven_spends),  # pylint: disable=no-member
                                            DelegatedPuzzleAndSolution(
                                                puzzle=Program.to(1),
                                                solution=Program.to(
                                                    [
                                                        announcement_2.to_program(),
                                                        announcement_1.corresponding_assertion().to_program(),
                                                    ]
                                                ),
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

        # couple of error cases
        with pytest.raises(ValueError, match=re.escape("M cannot be greater than N")):
            MofN(m=50, members=[])

        with pytest.raises(ValueError, match=re.escape("M must be greater than 0")):
            MofN(m=0, members=[])

        with pytest.raises(ValueError, match=re.escape("Duplicate nodes not currently supported by MofN drivers")):
            MofN(
                m=2,
                members=[
                    PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=ACSMember()),
                    PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=ACSMember()),
                ],
            )


@dataclass(frozen=True)
class ACSMemberValidator:
    member_not_dpuz: Literal[True] = field(init=False, default=True)

    def memo(self, nonce: int) -> Program:
        raise NotImplementedError  # pragma: no cover

    def puzzle(self, nonce: int) -> Program:
        # (mod (conditions . program) (a program conditions))
        return Program.to([2, 3, 2])

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
async def test_restriction_layer(cost_logger: CostLogger) -> None:
    """
    This tests the capabilities of the optional restriction layer placed on inner puzzles.
    """
    async with sim_and_client() as (sim, client):
        pwr = PuzzleWithRestrictions(
            nonce=0,
            restrictions=[ACSMemberValidator(), ACSMemberValidator(), ACSDPuzValidator(), ACSDPuzValidator()],
            puzzle=ACSMember(),
        )

        # Farm coin with puzzle inside
        await sim.farm_block(pwr.puzzle_hash())
        pwr_coin = (await client.get_coin_records_by_puzzle_hashes([pwr.puzzle_hash()], include_spent_coins=False))[
            0
        ].coin

        # Some announcements to make a ring between the delegated puzzle and the inner puzzle
        announcement_1 = CreateCoinAnnouncement(msg=b"foo", coin_id=pwr_coin.name())
        announcement_2 = CreateCoinAnnouncement(msg=b"bar", coin_id=pwr_coin.name())

        dpuz = Program.to(1)
        dpuzhash = dpuz.get_tree_hash()
        result = await client.push_tx(
            cost_logger.add_cost(
                "Puzzle with 4 restrictions (2 member validators & 2 dpuz validators) all ACS",
                WalletSpendBundle(
                    [
                        make_spend(
                            pwr_coin,
                            pwr.puzzle_reveal(),
                            pwr.solve(
                                [
                                    Program.to(None),
                                    # (mod conditions (r (r conditions)))
                                    # checks length >= 2
                                    Program.to(7),
                                ],
                                [
                                    Program.to(None),
                                    # (mod dpuzhash (if (= dpuzhash <dpuzhash>) () (x)))
                                    # (a (i (= 1 (q . <dpuzhash>)) () (q 8)) 1)
                                    Program.to([2, [3, [9, 1, (1, dpuzhash)], None, [1, 8]], 1]),
                                ],
                                Program.to(
                                    [
                                        announcement_1.to_program(),
                                        announcement_2.corresponding_assertion().to_program(),
                                    ]
                                ),
                                DelegatedPuzzleAndSolution(
                                    puzzle=dpuz,
                                    solution=Program.to(
                                        [
                                            announcement_2.to_program(),
                                            announcement_1.corresponding_assertion().to_program(),
                                        ]
                                    ),
                                ),
                            ),
                        )
                    ],
                    G2Element(),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)


def test_pwr_errors() -> None:
    PuzzleWithRestrictions.from_memo(  # sanity check
        Program.to((PuzzleWithRestrictions.spec_namespace, [0, [], None, [bytes32.zeros, None]]))
    )
    with pytest.raises(ValueError, match=re.escape("Attempting to parse a memo that does not belong to this spec")):
        PuzzleWithRestrictions.from_memo(Program.to("atom"))

    with pytest.raises(ValueError, match=re.escape("Attempting to parse a memo that does not belong to this spec")):
        PuzzleWithRestrictions.from_memo(Program.to(("not the namespace", None)))
