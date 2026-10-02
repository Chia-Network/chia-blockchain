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
    MIPSComponentBase,
    PuzzleWithRestrictions,
    PuzzleWithRestrictionsSolution,
)
from chia.wallet.puzzles.custody.restriction_utilities import (
    ValidatorStackRestriction,
    ValidatorStackRestrictionSolution,
)
from chia.wallet.puzzles.custody.restrictions import FixedCreateCoinDestinations, Heightlock, SendMessageBanned
from chia.wallet.puzzles.puzzle_drivers import (
    ACSSolution,
    DelegatedPuzzleAndSolution,
    NilPuzzle,
    NilSolution,
    P2Conditions,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


class EasyDPuzWrapper(MIPSComponentBase):
    @property
    def memo(self) -> Program:
        return Program.to(None)

    @property
    def program(self) -> Program:
        # (mod (conditions remark) (c (list REMARK remark) conditions)) -> (c (c (q . 1) (c 5 ())) 2)
        return Program.to([4, [4, (1, 1), [4, 5, None]], 2])

    @classmethod
    def match(cls, unknown_puzzle: UnknownPuzzle) -> EasyDPuzWrapper | None: ...


@pytest.mark.anyio
async def test_dpuz_validator_stack_restriction(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(required_wrappers=[EasyDPuzWrapper(), EasyDPuzWrapper()])
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], member=ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.tree_hash)
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.tree_hash], include_spent_coins=False))[0].coin

        # Attempt to just use any old dpuz
        any_old_dpuz = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(conditions=[Remark(rest=Program.to(["foo"]))]), solution=NilSolution()
        )
        not_wrapped_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.program,
                    PuzzleWithRestrictionsSolution(
                        member_solution=ACSSolution(conditions=[Remark(rest=Program.to(["bar"]))]),
                        delegated_puzzle_and_solution=any_old_dpuz,
                    ).program,
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(not_wrapped_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now actually put the dpuz in the wrapper
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(
            any_old_dpuz,
            [UnknownSolution(program=Program.to(["bat"])), UnknownSolution(program=Program.to(["baz"]))],
        )
        wrapped_spend = cost_logger.add_cost(
            "Minimal dpuz wrapper w/ wrapper stack enforcement",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.program,
                        PuzzleWithRestrictionsSolution(
                            dpuz_validator_solutions=[ValidatorStackRestrictionSolution.from_dpuz(any_old_dpuz.puzzle)],
                            member_solution=ACSSolution(conditions=[Remark(rest=Program.to(["bar"]))]),
                            delegated_puzzle_and_solution=wrapped_dpuz,
                        ).program,
                    )
                ],
                G2Element(),
            ),
        )
        result = await client.push_tx(wrapped_spend)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # memo format assertion for coverage sake
        assert restriction.memo == Program.to([None, None])

        # error check
        with pytest.raises(
            ValueError, match=re.escape("Number of wrapper solutions does not match number of required wrappers")
        ):
            restriction.modify_delegated_puzzle_and_solution(
                any_old_dpuz, [UnknownSolution(program=Program.to(["only one"]))]
            )


@pytest.mark.anyio
async def test_heightlock_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(required_wrappers=[Heightlock(heightlock=uint32(10))])
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], member=ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.tree_hash)
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.tree_hash], include_spent_coins=False))[0].coin

        # Attempt to just use any old dpuz
        any_old_dpuz = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(conditions=[Remark(rest=Program.to(["foo"]))]), solution=NilSolution()
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(any_old_dpuz, [NilSolution()])
        not_timelocked_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.program,
                    PuzzleWithRestrictionsSolution(
                        dpuz_validator_solutions=[ValidatorStackRestrictionSolution.from_dpuz(any_old_dpuz.puzzle)],
                        member_solution=ACSSolution(conditions=[Remark(rest=Program.to(["bar"]))]),
                        delegated_puzzle_and_solution=any_old_dpuz,
                    ).program,
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(not_timelocked_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now actually put a timelock in the dpuz
        timelocked_dpuz = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(
                conditions=[
                    AssertHeightRelative(height=uint32(10)),
                    Remark(rest=Program.to(["foo"])),
                    Remark(rest=Program.to(["bat"])),
                ],
            ),
            solution=NilSolution(),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(timelocked_dpuz, [NilSolution()])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ heightlock wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.program,
                        PuzzleWithRestrictionsSolution(
                            dpuz_validator_solutions=[
                                ValidatorStackRestrictionSolution.from_dpuz(timelocked_dpuz.puzzle)
                            ],
                            member_solution=ACSSolution(conditions=[Remark(rest=Program.to(["bar"]))]),
                            delegated_puzzle_and_solution=wrapped_dpuz,
                        ).program,
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
        assert restriction.memo == Program.to([None])


@pytest.mark.anyio
async def test_fixed_create_coin_wrapper(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(
            required_wrappers=[FixedCreateCoinDestinations(allowed_ph=bytes32.zeros)]
        )
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], member=ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.tree_hash)
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.tree_hash], include_spent_coins=False))[0].coin

        # Attempt to create a coin somewhere else
        any_old_dpuz = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(conditions=[CreateCoin(bytes32([1] * 32), uint64(1))]),
            solution=NilSolution(),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(any_old_dpuz, [NilSolution()])
        escape_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.program,
                    PuzzleWithRestrictionsSolution(
                        dpuz_validator_solutions=[ValidatorStackRestrictionSolution.from_dpuz(any_old_dpuz.puzzle)],
                        member_solution=ACSSolution(conditions=[Remark(rest=Program.to(["bar"]))]),
                        delegated_puzzle_and_solution=any_old_dpuz,
                    ).program,
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(escape_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now send it to the correct place
        correct_dpuz = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(conditions=[CreateCoin(bytes32.zeros, uint64(1)), Remark(Program.to("foo"))]),
            solution=NilSolution(),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(correct_dpuz, [NilSolution()])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ fixed create coin wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.program,
                        PuzzleWithRestrictionsSolution(
                            dpuz_validator_solutions=[ValidatorStackRestrictionSolution.from_dpuz(correct_dpuz.puzzle)],
                            member_solution=ACSSolution(conditions=[Remark(Program.to("bar"))]),
                            delegated_puzzle_and_solution=wrapped_dpuz,
                        ).program,
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
        assert restriction.memo == Program.to([None])


@pytest.mark.anyio
async def test_send_message_banned(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        restriction = ValidatorStackRestriction(required_wrappers=[SendMessageBanned()])
        pwr = PuzzleWithRestrictions(nonce=0, restrictions=[restriction], member=ACSMember())

        # Farm and find coin
        await sim.farm_block(pwr.tree_hash)
        coin = (await client.get_coin_records_by_puzzle_hashes([pwr.tree_hash], include_spent_coins=False))[0].coin

        # Attempt to send a message
        send_message_dpuz = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(
                conditions=[
                    SendMessage(
                        bytes32.zeros,
                        sender=MessageParticipant(parent_id_committed=bytes32.zeros),
                        receiver=MessageParticipant(parent_id_committed=bytes32.zeros),
                    )
                ]
            ),
            solution=NilSolution(),
        )
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(send_message_dpuz, [NilSolution()])
        escape_attempt = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    pwr.program,
                    PuzzleWithRestrictionsSolution(
                        dpuz_validator_solutions=[
                            ValidatorStackRestrictionSolution.from_dpuz(send_message_dpuz.puzzle)
                        ],
                        member_solution=NilSolution(),
                        delegated_puzzle_and_solution=wrapped_dpuz,
                    ).program,
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(escape_attempt)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Now send it to the correct place
        self_destruct_dpuz = DelegatedPuzzleAndSolution(puzzle=NilPuzzle(), solution=NilSolution())
        wrapped_dpuz = restriction.modify_delegated_puzzle_and_solution(self_destruct_dpuz, [NilSolution()])
        sb = cost_logger.add_cost(
            "Minimal puzzle with restrictions w/ send message banned wrapper",
            WalletSpendBundle(
                [
                    make_spend(
                        coin,
                        pwr.program,
                        PuzzleWithRestrictionsSolution(
                            dpuz_validator_solutions=[
                                ValidatorStackRestrictionSolution.from_dpuz(self_destruct_dpuz.puzzle)
                            ],
                            member_solution=NilSolution(),
                            delegated_puzzle_and_solution=wrapped_dpuz,
                        ).program,
                    )
                ],
                G2Element(),
            ),
        )
        result = await client.push_tx(sb)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # memo format assertion for coverage sake
        assert restriction.memo == Program.to([None])
