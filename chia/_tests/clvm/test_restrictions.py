from __future__ import annotations

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
from chia.wallet.puzzles.custody.custody_architecture import DelegatedPuzzleAndSolution, PuzzleWithRestrictions
from chia.wallet.puzzles.custody.restriction_puzzles.restrictions import Timelock
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
