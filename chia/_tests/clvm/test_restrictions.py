from __future__ import annotations

import re

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.clvm.test_custody_architecture import ACSMember
from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.conditions import (
    AssertHeightRelative,
    CreateCoin,
    MessageParticipant,
    Remark,
    SendMessage,
    parse_conditions_non_consensus,
)
from chia.wallet.puzzles.custody.custody_architecture import (
    DelegatedPuzzleAndSolution,
    PuzzleWithRestrictions,
)
from chia.wallet.puzzles.custody.restriction_utilities import ValidatorStackRestriction
from chia.wallet.puzzles.custody.restrictions import FixedCreateCoinDestinations, Heightlock, SendMessageBanned
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
                            [restriction.solve(original_dpuz=any_old_dpuz.puzzle)],
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

        # error check
        with pytest.raises(
            ValueError, match=re.escape("Number of wrapper solutions does not match number of required wrappers")
        ):
            restriction.modify_delegated_puzzle_and_solution(any_old_dpuz, [Program.to(["only one"])])


@pytest.mark.anyio
async def test_heightlock_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(required_wrappers=[Heightlock(heightlock=uint32(10))])
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
            puzzle=Program.to((1, [AssertHeightRelative(height=uint32(10)).to_program(), [1, "foo"], [1, "bat"]])),
            solution=Program.to(None),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(timelocked_dpuz, [Program.to(None)])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ heightlock wrapper",
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
        assert result == (MempoolInclusionStatus.PENDING, Err.ASSERT_HEIGHT_RELATIVE_FAILED)
        for _ in range(10):
            await sim.farm_block()
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()

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
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(send_message_dpuz, [Program.to(None)])
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
