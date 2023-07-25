from __future__ import annotations

from typing import Dict, Optional, Tuple

import pytest
from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.clvm.spend_sim import CostLogger, SimClient, SpendSim, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.util.misc import VersionedBlob
from chia.wallet.puzzles.clawback.drivers import (
    create_augmented_cond_puzzle_hash,
    create_clawback_merkle_tree,
    create_merkle_puzzle,
    create_merkle_solution,
    create_p2_puzzle_hash_puzzle,
    match_clawback_puzzle,
)
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata, ClawbackVersion
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.merkle_utils import check_merkle_proof
from chia.wallet.util.wallet_types import RemarkDataType
from tests.clvm.benchmark_costs import cost_of_spend_bundle
from tests.clvm.test_puzzles import public_key_for_index, secret_exponent_for_index
from tests.util.key_tool import KeyTool

ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


async def do_spend(
    sim: SpendSim,
    sim_client: SimClient,
    spend_bundle: SpendBundle,
    expected_result: Tuple[MempoolInclusionStatus, Optional[Err]],
    cost_logger: Optional[CostLogger] = None,
    cost_log_msg: str = "",
) -> int:
    if cost_logger is not None:
        spend_bundle = cost_logger.add_cost(cost_log_msg, spend_bundle)
    result = await sim_client.push_tx(spend_bundle)
    assert result == expected_result
    cost = cost_of_spend_bundle(spend_bundle)
    height = sim.get_height()
    await sim.farm_block()
    await time_out_assert(10, sim.get_height, height + 1)
    return cost


class TestClawbackLifecycle:
    # Helper function
    def sign_coin_spend(self, coin_spend: CoinSpend, index: int) -> G2Element:
        synthetic_secret_key: PrivateKey = calculate_synthetic_secret_key(  # noqa
            PrivateKey.from_bytes(
                secret_exponent_for_index(index).to_bytes(32, "big"),
            ),
            DEFAULT_HIDDEN_PUZZLE_HASH,
        )

        conditions_dict = conditions_dict_for_solution(coin_spend.puzzle_reveal, coin_spend.solution, INFINITE_COST)
        signatures = []
        for pk_bytes, msg in pkm_pairs_for_conditions_dict(
            conditions_dict, coin_spend.coin, DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
        ):
            pk = G1Element.from_bytes(pk_bytes)
            signature = AugSchemeMPL.sign(synthetic_secret_key, msg)
            assert AugSchemeMPL.verify(pk, msg, signature)
            signatures.append(signature)
        return AugSchemeMPL.aggregate(signatures)

    @pytest.mark.asyncio()
    async def test_clawback_spends(self, cost_logger: CostLogger) -> None:
        async with sim_and_client() as (sim, sim_client):
            key_lookup = KeyTool()  # type: ignore[no-untyped-call]
            sender_index = 1
            sender_pk = G1Element(public_key_for_index(sender_index, key_lookup))
            sender_puz = puzzle_for_pk(sender_pk)
            sender_ph = sender_puz.get_tree_hash()
            recipient_index = 2
            recipient_pk = G1Element(public_key_for_index(recipient_index, key_lookup))
            recipient_puz = puzzle_for_pk(recipient_pk)
            recipient_ph = recipient_puz.get_tree_hash()

            await sim.farm_block(sender_ph)
            starting_coin = (await sim_client.get_coin_records_by_puzzle_hash(sender_ph))[0].coin

            timelock = uint64(100)
            amount = uint64(10000000)
            cb_puzzle = create_merkle_puzzle(timelock, sender_ph, recipient_ph)
            cb_puz_hash = cb_puzzle.get_tree_hash()

            sender_invalid_sol = solution_for_conditions(
                [
                    [ConditionOpcode.CREATE_COIN, cb_puz_hash, amount],
                    [ConditionOpcode.REMARK.value, RemarkDataType.CLAWBACK, b"Test"],
                ]
            )
            sender_sol = solution_for_conditions(
                [
                    [ConditionOpcode.CREATE_COIN, cb_puz_hash, amount],
                    [
                        ConditionOpcode.REMARK.value,
                        RemarkDataType.CLAWBACK,
                        bytes(
                            VersionedBlob(
                                ClawbackVersion.V1.value, bytes(ClawbackMetadata(timelock, sender_ph, recipient_ph))
                            )
                        ),
                    ],
                ]
            )
            coin_spend = CoinSpend(starting_coin, sender_puz, sender_sol)
            sig = self.sign_coin_spend(coin_spend, sender_index)
            spend_bundle = SpendBundle([coin_spend], sig)

            await do_spend(
                sim,
                sim_client,
                spend_bundle,
                (MempoolInclusionStatus.SUCCESS, None),
                cost_logger=cost_logger,
                cost_log_msg="Create First Clawback",
            )

            # Fetch the clawback coin
            clawback_coin = (await sim_client.get_coin_records_by_puzzle_hash(cb_puz_hash))[0].coin
            assert clawback_coin.amount == amount
            # Test match_clawback_puzzle
            clawback_metadata = match_clawback_puzzle(uncurry_puzzle(sender_puz), sender_puz, sender_sol)
            assert clawback_metadata is not None
            assert clawback_metadata.time_lock == timelock
            assert clawback_metadata.sender_puzzle_hash == sender_ph
            assert clawback_metadata.recipient_puzzle_hash == recipient_ph
            clawback_metadata = match_clawback_puzzle(uncurry_puzzle(sender_puz), sender_puz, sender_invalid_sol)
            assert clawback_metadata is None
            # Fail an early claim spend
            recipient_sol = solution_for_conditions([[ConditionOpcode.CREATE_COIN, recipient_ph, amount]])
            claim_sol = create_merkle_solution(timelock, sender_ph, recipient_ph, recipient_puz, recipient_sol)
            coin_spend = CoinSpend(clawback_coin, cb_puzzle, claim_sol)
            sig = self.sign_coin_spend(coin_spend, recipient_index)
            spend_bundle = SpendBundle([coin_spend], sig)

            await do_spend(
                sim,
                sim_client,
                spend_bundle,
                (MempoolInclusionStatus.FAILED, Err.ASSERT_SECONDS_RELATIVE_FAILED),
                cost_logger=cost_logger,
                cost_log_msg="Early Claim",
            )

            # Pass time and submit successful claim spend
            sim.pass_time(uint64(110))
            await sim.farm_block()
            await do_spend(
                sim,
                sim_client,
                spend_bundle,
                (MempoolInclusionStatus.SUCCESS, None),
                cost_logger=cost_logger,
                cost_log_msg="Successful Claim",
            )

            # check the claimed coin is found
            claimed_coin = (await sim_client.get_coin_records_by_puzzle_hash(recipient_ph))[0].coin
            assert claimed_coin.amount == amount

            # create another clawback coin and claw it back to a "cold wallet"
            cold_ph = bytes32([1] * 32)
            new_coin = (await sim_client.get_coin_records_by_puzzle_hash(sender_ph, include_spent_coins=False))[0].coin
            coin_spend = CoinSpend(new_coin, sender_puz, sender_sol)
            sig = self.sign_coin_spend(coin_spend, sender_index)
            spend_bundle = SpendBundle([coin_spend], sig)

            await do_spend(
                sim,
                sim_client,
                spend_bundle,
                (MempoolInclusionStatus.SUCCESS, None),
                cost_logger=cost_logger,
                cost_log_msg="Create Second Clawback",
            )

            new_cb_coin = (await sim_client.get_coin_records_by_puzzle_hash(cb_puz_hash, include_spent_coins=False))[
                0
            ].coin

            sender_claw_sol = solution_for_conditions([[ConditionOpcode.CREATE_COIN, cold_ph, amount]])
            claw_sol = create_merkle_solution(timelock, sender_ph, recipient_ph, sender_puz, sender_claw_sol)
            coin_spend = CoinSpend(new_cb_coin, cb_puzzle, claw_sol)
            sig = self.sign_coin_spend(coin_spend, sender_index)
            spend_bundle = SpendBundle([coin_spend], sig)

            await do_spend(
                sim,
                sim_client,
                spend_bundle,
                (MempoolInclusionStatus.SUCCESS, None),
                cost_logger=cost_logger,
                cost_log_msg="Clawback Second Coin to cold ph",
            )

            clawed_coin = (await sim_client.get_coin_records_by_puzzle_hash(cold_ph))[0].coin
            assert clawed_coin.amount == amount

    def test_merkle_puzzles(self) -> None:
        # set up test info
        timelock = uint64(100)
        sender_ph = bytes32([1] * 32)
        recipient_ph = bytes32([2] * 32)
        # create the puzzles which go into the merkle tree
        claw_puz_hash = create_p2_puzzle_hash_puzzle(sender_ph).get_tree_hash()
        claim_puz_hash = create_augmented_cond_puzzle_hash([80, timelock], recipient_ph)
        # create and check the merkle root and proofs
        merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
        bad_proof = (1, [claim_puz_hash])
        clawback_proof = merkle_tree.generate_proof(claw_puz_hash)
        assert clawback_proof[0] is not None
        assert len(clawback_proof[1]) == 1
        assert clawback_proof[1][0] is not None

        claim_proof = merkle_tree.generate_proof(claim_puz_hash)
        assert claim_proof[0] is not None
        assert len(claim_proof[1]) == 1
        assert claim_proof[1][0] is not None

        assert check_merkle_proof(
            merkle_tree.calculate_root(), claw_puz_hash, (clawback_proof[0], clawback_proof[1][0])
        )
        assert check_merkle_proof(merkle_tree.calculate_root(), claim_puz_hash, (claim_proof[0], claim_proof[1][0]))
        assert not check_merkle_proof(merkle_tree.calculate_root(), claim_puz_hash, bad_proof)

        # check we can't use a timelock less than 1
        bad_timelock = uint64(0)
        with pytest.raises(ValueError) as exc_info:
            create_clawback_merkle_tree(bad_timelock, sender_ph, recipient_ph)
        assert exc_info.value.args[0] == "Timelock must be at least 1 second"

    def test_clawback_puzzles(self) -> None:
        timelock = uint64(100)
        amount = uint64(1000)
        pk = G1Element()
        sender_puz = puzzle_for_pk(pk)
        sender_ph = sender_puz.get_tree_hash()
        recipient_puz = ACS
        recipient_ph = ACS_PH

        clawback_puz = create_merkle_puzzle(timelock, sender_ph, recipient_ph)

        sender_sol = solution_for_conditions(
            [
                [51, sender_ph, amount],
            ]
        )
        # Test invalid puzzle
        has_exception = False
        try:
            create_merkle_solution(timelock, sender_ph, recipient_ph, Program.to([]), sender_sol)
        except ValueError:
            has_exception = True
        assert has_exception
        cb_sender_sol = create_merkle_solution(timelock, sender_ph, recipient_ph, sender_puz, sender_sol)

        conds = conditions_dict_for_solution(clawback_puz, cb_sender_sol, INFINITE_COST)
        assert isinstance(conds, Dict)
        create_coins = conds[ConditionOpcode.CREATE_COIN]
        assert len(create_coins) == 1
        assert create_coins[0].vars[0] == sender_ph

        recipient_sol = Program.to([[51, recipient_ph, amount]])
        cb_recipient_sol = create_merkle_solution(timelock, sender_ph, recipient_ph, recipient_puz, recipient_sol)
        clawback_puz.run(cb_recipient_sol)
        conds = conditions_dict_for_solution(clawback_puz, cb_recipient_sol, INFINITE_COST)
        assert isinstance(conds, Dict)
        create_coins = conds[ConditionOpcode.CREATE_COIN]
        assert len(create_coins) == 1
        assert create_coins[0].vars[0] == recipient_ph
