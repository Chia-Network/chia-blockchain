from __future__ import annotations

from dataclasses import dataclass

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32

from chia._tests.clvm.test_custody_architecture import ACSMember
from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.conditions import CreateCoin, CreateCoinAnnouncement
from chia.wallet.puzzles.custody.custody_architecture import (
    DelegatedPuzzleAndSolution,
    MemberOrDPuz,
    MofN,
    ProvenSpend,
    PuzzleWithRestrictions,
    Restriction,
)
from chia.wallet.puzzles.custody.restriction_puzzles.restrictions import (
    Force1of2wRestrictedVariable,
    ForceCoinAnnouncement,
    Timelock,
)
from chia.wallet.puzzles.custody.restriction_utilities import ValidatorStackRestriction
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


class EasyDPuzWrapper:
    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        # (mod (conditions remark) (c (list REMARK remark) conditions)) -> (c (c (q . 1) (c 5 ())) 2)
        return Program.to([4, [4, (1, 1), [4, 5, None]], 2])

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
async def test_dpuz_validator_stack_restriction(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction([EasyDPuzWrapper()])
        pwr = PuzzleWithRestrictions(0, [restriction], ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.puzzle_hash()], include_spent_coins=False))[0].coin

        # Attempt to just use any old dpuz
        any_old_dpuz = DelegatedPuzzleAndSolution(puzzle=Program.to((1, [[1, "foo"]])), solution=Program.to(None))
        not_wrapped_attempt = WalletSpendBundle(
            [make_spend(coin, pwr.puzzle_reveal(), pwr.solve([], [], Program.to([[1, "bar"]]), any_old_dpuz))],
            G2Element(),
        )
        result = await client.push_tx(not_wrapped_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now actually put the dpuz in the wrapper
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(any_old_dpuz, [Program.to(["bat"])])
        wrapped_spend = cost_logger.add_cost(
            "Minimal dpuz wrapper w/ wrapper stack enforcement",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.puzzle_reveal(),
                        pwr.solve(
                            [],
                            [Program.to([any_old_dpuz.puzzle.get_tree_hash()])],
                            Program.to([[1, "bar"]]),
                            wrapped_dpuz,
                        ),
                    )
                ],
                G2Element(),
            ),
        )
        result = await client.push_tx(wrapped_spend)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # memo format assertion for coverage sake
        assert restriction.memo(0) == Program.to([None])


@pytest.mark.anyio
async def test_timelock_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction([Timelock(uint64(100))])
        pwr = PuzzleWithRestrictions(0, [restriction], ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.puzzle_hash()], include_spent_coins=False))[0].coin

        # Attempt to just use any old dpuz
        any_old_dpuz = DelegatedPuzzleAndSolution(puzzle=Program.to((1, [[1, "foo"]])), solution=Program.to(None))
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(any_old_dpuz, [Program.to(None)])
        not_timelocked_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.puzzle_reveal(),
                    pwr.solve(
                        [], [Program.to([any_old_dpuz.puzzle.get_tree_hash()])], Program.to([[1, "bar"]]), any_old_dpuz
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(not_timelocked_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now actually put a timelock in the dpuz
        timelocked_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to((1, [[80, 100], [1, "foo"]])), solution=Program.to(None)
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(timelocked_dpuz, [Program.to(None)])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ timelock wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.puzzle_reveal(),
                        pwr.solve(
                            [],
                            [Program.to([timelocked_dpuz.puzzle.get_tree_hash()])],
                            Program.to([[1, "bar"]]),
                            wrapped_dpuz,
                        ),
                    )
                ],
                G2Element(),
            ),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_SECONDS_RELATIVE_FAILED)

        sim.pass_time(uint64(100))
        await sim.farm_block()
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # memo format assertion for coverage sake
        assert restriction.memo(0) == Program.to([None])


@pytest.mark.anyio
async def test_force_coin_announcement_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction([ForceCoinAnnouncement()])
        pwr = PuzzleWithRestrictions(0, [restriction], ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.puzzle_hash()], include_spent_coins=False))[0].coin

        # Attempt to just use any old dpuz
        any_old_dpuz = DelegatedPuzzleAndSolution(puzzle=Program.to((1, [[1, "foo"]])), solution=Program.to(None))
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(any_old_dpuz, [Program.to(None)])
        not_timelocked_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.puzzle_reveal(),
                    pwr.solve(
                        [], [Program.to([any_old_dpuz.puzzle.get_tree_hash()])], Program.to([[1, "bar"]]), any_old_dpuz
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(not_timelocked_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now actually put a coin announcement in the dpuz
        announcement = CreateCoinAnnouncement(bytes32.zeros, coin_id=coin.name())
        announcement_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to(
                (1, [announcement.to_program(), announcement.corresponding_assertion().to_program(), [1, "foo"]])
            ),
            solution=Program.to(None),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(announcement_dpuz, [Program.to(None)])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ coin announcement forcing wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.puzzle_reveal(),
                        pwr.solve(
                            [],
                            [Program.to([announcement_dpuz.puzzle.get_tree_hash()])],
                            Program.to([[1, "bar"]]),
                            wrapped_dpuz,
                        ),
                    )
                ],
                G2Element(),
            ),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # memo format assertion for coverage sake
        assert restriction.memo(0) == Program.to([None])


@dataclass(frozen=True)
class SelfDestructRestriction:
    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        # (mod
        #   (Delegated_Puzzle_Hash)
        #   (if (= Delegated_Puzzle_Hash (sha256 1 ()))
        #       ()
        #       (x "only self destruct allowed")
        #   )
        # )
        return Program.fromhex(
            "ff02ffff03ffff09ff02ffff01a04bf5122f344554c53bde2ebb8cd2b7e3d1600ad631c385a5d7cce23c7785459a80ff80ffff01ff08ffff019a6f6e6c792073656c6620646573747275637420616c6c6f7765648080ff0180"
        )

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class ConditionsBannedRestriction:
    @property
    def member_not_dpuz(self) -> bool:
        return True

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        # (mod
        #   (Conditions)
        #   (if (= Conditions ())
        #       ()
        #       (x "conditions banned")
        #   )
        # )
        return Program.fromhex(
            "ff02ffff03ffff09ff02ff8080ff80ffff01ff08ffff0191636f6e646974696f6e732062616e6e65648080ff0180"
        )

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
async def test_force_1_of_2_w_restricted_variable_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        # What our puzzle must be
        anticipated_left_side_pwr = PuzzleWithRestrictions(0, [], ACSMember())
        anticipated_restrictions: list[Restriction[MemberOrDPuz]] = [
            SelfDestructRestriction(),
            ConditionsBannedRestriction(),
        ]
        anticipated_right_side_pwr = PuzzleWithRestrictions(0, anticipated_restrictions, ACSMember())
        anticipated_m_of_n = MofN(m=1, members=[anticipated_left_side_pwr, anticipated_right_side_pwr])
        anticipated_pwr = PuzzleWithRestrictions(0, [], anticipated_m_of_n)

        # The current puzzle
        restriction = ValidatorStackRestriction(
            [
                Force1of2wRestrictedVariable(
                    left_side_hash=anticipated_left_side_pwr.puzzle_hash(_top_level=False),
                    right_side_restrictions=anticipated_restrictions,
                )
            ]
        )
        pwr = PuzzleWithRestrictions(0, [restriction], ACSMember())
        pwr_hash = pwr.puzzle_hash()

        # Farm and find coin
        await sim.farm_block(pwr.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr_hash], include_spent_coins=False))[0].coin

        # Attempt to just recreate ourselves
        recreation_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to((1, [CreateCoin(pwr_hash, uint64(0)).to_program()])), solution=Program.to(None)
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(
            recreation_dpuz, [Program.to([ACSMember().puzzle_hash(0)])]
        )
        recreation_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.puzzle_reveal(),
                    pwr.solve(
                        [], [Program.to([recreation_dpuz.puzzle.get_tree_hash()])], Program.to(None), recreation_dpuz
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(recreation_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now actually send to the correct puzzle hash
        anticipated_pwr_hash = anticipated_pwr.puzzle_hash()
        correct_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to((1, [CreateCoin(anticipated_pwr_hash, uint64(0)).to_program()])),
            solution=Program.to(None),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(
            correct_dpuz, [Program.to([ACSMember().puzzle_hash(0)])]
        )
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ 1 of 2 w/ restricted variable forcing wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.puzzle_reveal(),
                        pwr.solve(
                            [],
                            [Program.to([correct_dpuz.puzzle.get_tree_hash()])],
                            Program.to(None),
                            wrapped_dpuz,
                        ),
                    )
                ],
                G2Element(),
            ),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # Farm and find coin
        await sim.farm_block(bytes32.zeros)
        anticipated_coin = (
            await client.get_coin_records_by_puzzle_hashes([anticipated_pwr_hash], include_spent_coins=False)
        )[0].coin

        # Now test whether or not the right side is actually restricted (dpuz restriction)
        any_old_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to((1, [[1, "foo"]])),  # This shouldn't be allowed by SelfDestructRestriction
            solution=Program.to(None),
        )

        sb = WalletSpendBundle(
            [
                make_spend(
                    anticipated_coin,
                    anticipated_pwr.puzzle_reveal(),
                    anticipated_pwr.solve(
                        [],
                        [],
                        anticipated_m_of_n.solve(
                            {
                                anticipated_right_side_pwr.puzzle_hash(_top_level=False): ProvenSpend(
                                    anticipated_right_side_pwr.puzzle_reveal(_top_level=False),
                                    anticipated_right_side_pwr.solve(
                                        [Program.to(None)],
                                        [Program.to(None)],
                                        Program.to([]),  # This should pass ConditionsBannedRestriction
                                    ),
                                )
                            }
                        ),
                        any_old_dpuz,
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now test whether or not the right side is actually restricted (member restriction)
        valid_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to(None),  # This should pass SelfDestructRestriction
            solution=Program.to(None),
        )

        sb = WalletSpendBundle(
            [
                make_spend(
                    anticipated_coin,
                    anticipated_pwr.puzzle_reveal(),
                    anticipated_pwr.solve(
                        [],
                        [],
                        anticipated_m_of_n.solve(
                            {
                                anticipated_right_side_pwr.puzzle_hash(_top_level=False): ProvenSpend(
                                    anticipated_right_side_pwr.puzzle_reveal(_top_level=False),
                                    anticipated_right_side_pwr.solve(
                                        [Program.to(None)],
                                        [Program.to(None)],
                                        Program.to(
                                            [[1, "foo"]]
                                        ),  # This should be banned by ConditionsBannedRestriction
                                    ),
                                )
                            }
                        ),
                        valid_dpuz,
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now test we can make a successful spend from the right side
        sb = WalletSpendBundle(
            [
                make_spend(
                    anticipated_coin,
                    anticipated_pwr.puzzle_reveal(),
                    anticipated_pwr.solve(
                        [],
                        [],
                        anticipated_m_of_n.solve(
                            {
                                anticipated_right_side_pwr.puzzle_hash(_top_level=False): ProvenSpend(
                                    anticipated_right_side_pwr.puzzle_reveal(_top_level=False),
                                    anticipated_right_side_pwr.solve(
                                        [Program.to(None)],
                                        [Program.to(None)],
                                        Program.to([]),  # This should pass ConditionsBannedRestriction
                                    ),
                                )
                            }
                        ),
                        valid_dpuz,
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # Rewind that last spend
        block_height = sim.block_height
        await sim.farm_block()
        await sim.rewind(block_height)

        # And for posterity, let's make sure we can spend from the left as well
        some_puzzle_hash = bytes32([1] * 32)
        sb = WalletSpendBundle(
            [
                make_spend(
                    anticipated_coin,
                    anticipated_pwr.puzzle_reveal(),
                    anticipated_pwr.solve(
                        [],
                        [],
                        anticipated_m_of_n.solve(
                            {
                                anticipated_left_side_pwr.puzzle_hash(_top_level=False): ProvenSpend(
                                    anticipated_left_side_pwr.puzzle_reveal(_top_level=False),
                                    anticipated_left_side_pwr.solve(
                                        [],
                                        [],
                                        Program.to([CreateCoin(some_puzzle_hash, uint64(0)).to_program()]),
                                    ),
                                )
                            }
                        ),
                        valid_dpuz,
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # Farm and find coin
        await sim.farm_block(bytes32.zeros)
        assert len(await client.get_coin_records_by_puzzle_hashes([some_puzzle_hash], include_spent_coins=False)) > 0
