from __future__ import annotations

from dataclasses import dataclass

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.clvm.test_custody_architecture import ACSMember
from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.pools.plotnft_drivers import SendMessageBanned
from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.conditions import CreateCoin, MessageParticipant, Remark, SendMessage, parse_conditions_non_consensus
from chia.wallet.puzzles.custody.custody_architecture import (
    DelegatedPuzzleAndSolution,
    MemberOrDPuz,
    MofN,
    ProvenSpend,
    PuzzleWithRestrictions,
    Restriction,
    UnknownRestriction,
)
from chia.wallet.puzzles.custody.restriction_utilities import ValidatorStackRestriction
from chia.wallet.puzzles.custody.restrictions import FixedCreateCoinDestinations, Force1of2wRestrictedVariable, Timelock
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
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
        restriction = ValidatorStackRestriction(required_wrappers=[EasyDPuzWrapper(), EasyDPuzWrapper()])
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], puzzle=ACSMember())

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
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(
            any_old_dpuz, [Program.to(["bat"]), Program.to(["baz"])]
        )
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
        assert restriction.memo(0) == Program.to([None, None])


@pytest.mark.anyio
async def test_timelock_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(required_wrappers=[Timelock(uint64(100))])
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], puzzle=ACSMember())

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
            puzzle=Program.to((1, [[80, 100], [1, "foo"], [1, "bat"]])), solution=Program.to(None)
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

        conditions = parse_conditions_non_consensus(
            run(sb.coin_spends[0].puzzle_reveal, sb.coin_spends[0].solution).as_iter()
        )
        assert Remark(Program.to(["foo"])) in conditions
        assert Remark(Program.to(["bar"])) in conditions
        assert Remark(Program.to(["bat"])) in conditions

        # memo format assertion for coverage sake
        assert restriction.memo(0) == Program.to([None])


@pytest.mark.anyio
async def test_fixed_create_coin_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(
            required_wrappers=[FixedCreateCoinDestinations(allowed_ph=bytes32.zeros)]
        )
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], puzzle=ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.puzzle_hash()], include_spent_coins=False))[0].coin

        # Attempt to create a coin somewhere else
        any_old_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to((1, [CreateCoin(bytes32([1] * 32), uint64(1)).to_program()])), solution=Program.to(None)
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(any_old_dpuz, [Program.to(None)])
        escape_attempt = WalletSpendBundle(
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
        result = await client.push_tx(escape_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now send it to the correct place
        correct_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to(
                (1, [CreateCoin(bytes32.zeros, uint64(1)).to_program(), Remark(Program.to("foo")).to_program()])
            ),
            solution=Program.to(None),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(correct_dpuz, [Program.to(None)])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ fixed create coin wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.puzzle_reveal(),
                        pwr.solve(
                            [],
                            [Program.to([correct_dpuz.puzzle.get_tree_hash()])],
                            Program.to([Remark(Program.to("bar")).to_program()]),
                            wrapped_dpuz,
                        ),
                    )
                ],
                G2Element(),
            ),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        conditions = parse_conditions_non_consensus(
            run(sb.coin_spends[0].puzzle_reveal, sb.coin_spends[0].solution).as_iter()
        )
        assert Remark(Program.to("foo")) in conditions
        assert Remark(Program.to("bar")) in conditions

        # memo format assertion for coverage sake
        assert restriction.memo(0) == Program.to([None])


@pytest.mark.anyio
async def test_send_message_banned(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(required_wrappers=[SendMessageBanned()])
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], puzzle=ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.puzzle_hash()], include_spent_coins=False))[0].coin

        # Attempt to send a message
        send_message_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to(
                (
                    1,
                    [
                        SendMessage(
                            bytes32.zeros,
                            sender=MessageParticipant(parent_id_committed=bytes32.zeros),
                            receiver=MessageParticipant(parent_id_committed=bytes32.zeros),
                        ).to_program()
                    ],
                )
            ),
            solution=Program.to(None),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(
            send_message_dpuz, [Program.to(None), Program.to(None)]
        )
        escape_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.puzzle_reveal(),
                    pwr.solve(
                        [],
                        [Program.to([send_message_dpuz.puzzle.get_tree_hash()])],
                        Program.to(None),
                        wrapped_dpuz,
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(escape_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now send it to the correct place
        self_destruct_dpuz = DelegatedPuzzleAndSolution(
            puzzle=Program.to(None),
            solution=Program.to(None),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(self_destruct_dpuz, [Program.to(None)])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ send message banned wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.puzzle_reveal(),
                        pwr.solve(
                            [],
                            [Program.to([self_destruct_dpuz.puzzle.get_tree_hash()])],
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
        return load_clvm_maybe_recompile("self_destruct.clsp", package_or_requirement="chia._tests.clvm.puzzles")

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
        return load_clvm_maybe_recompile("conditions_banned.clsp", package_or_requirement="chia._tests.clvm.puzzles")

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@pytest.mark.anyio
async def test_force_1_of_2_w_restricted_variable_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        # What our puzzle must be
        anticipated_left_side_pwr = PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=ACSMember())
        anticipated_restrictions: list[Restriction[MemberOrDPuz]] = [
            SelfDestructRestriction(),
            ConditionsBannedRestriction(),
        ]
        recovery_restriction = Force1of2wRestrictedVariable(
            left_side_hash=anticipated_left_side_pwr.puzzle_hash(_top_level=False),
            right_side_restrictions=anticipated_restrictions,
        )
        anticipated_pwr = recovery_restriction.anticipated_pwr(0, anticipated_left_side_pwr, ACSMember())
        anticipated_m_of_n = anticipated_pwr.puzzle
        assert isinstance(anticipated_m_of_n, MofN)
        anticipated_right_side_pwr = anticipated_m_of_n.members[1]

        # The current puzzle
        restriction = ValidatorStackRestriction(required_wrappers=[recovery_restriction])
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], puzzle=ACSMember())
        pwr_hash = pwr.puzzle_hash()

        # Some brief memo checking
        parsed_pwr = PuzzleWithRestrictions.from_memo(pwr.memo())
        assert isinstance(parsed_pwr.restrictions[0], UnknownRestriction)
        parsed_recovery_restriction = Force1of2wRestrictedVariable.from_memo(
            parsed_pwr.restrictions[0].restriction_hint.memo.first(), recovery_restriction.left_side_hash
        )
        assert recovery_restriction == parsed_recovery_restriction.fill_in_unknown_puzzles(
            {
                SelfDestructRestriction().puzzle_hash(0): SelfDestructRestriction(),
                ConditionsBannedRestriction().puzzle_hash(0): ConditionsBannedRestriction(),
            }
        )

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
            puzzle=Program.to((1, [CreateCoin(anticipated_pwr_hash, uint64(0), []).to_program()])),
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
                                    puzzle_reveal=anticipated_right_side_pwr.puzzle_reveal(_top_level=False),
                                    solution=anticipated_right_side_pwr.solve(
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
                                    puzzle_reveal=anticipated_right_side_pwr.puzzle_reveal(_top_level=False),
                                    solution=anticipated_right_side_pwr.solve(
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
                                    puzzle_reveal=anticipated_right_side_pwr.puzzle_reveal(_top_level=False),
                                    solution=anticipated_right_side_pwr.solve(
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
                                    puzzle_reveal=anticipated_left_side_pwr.puzzle_reveal(_top_level=False),
                                    solution=anticipated_left_side_pwr.solve(
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
