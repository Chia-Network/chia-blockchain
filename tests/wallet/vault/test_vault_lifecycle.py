from __future__ import annotations

from hashlib import sha256
from typing import Optional, Tuple

import pytest
from chia_rs import AugSchemeMPL, G2Element, PrivateKey
from clvm.casts import int_to_bytes
from ecdsa import NIST256p, SigningKey

from chia.clvm.spend_sim import CostLogger, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions, solution_for_conditions
from chia.wallet.vault.vault_drivers import (
    construct_p2_delegated_secp,
    construct_p2_recovery_puzzle,
    construct_recovery_finish,
    construct_secp_message,
    construct_vault_merkle_tree,
    construct_vault_puzzle,
    get_vault_proof,
)
from tests.clvm.test_puzzles import secret_exponent_for_index

SECP_SK = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
SECP_PK = SECP_SK.verifying_key.to_string("compressed")

BLS_SK = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
BLS_PK = BLS_SK.get_g1()

TIMELOCK = uint64(1000)
ACS = Program.to(0)
ACS_PH = ACS.get_tree_hash()
ENTROPY = int_to_bytes(101)


@pytest.mark.anyio
async def test_vault_inner(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        sim.pass_blocks(DEFAULT_CONSTANTS.SOFT_FORK2_HEIGHT)  # Make sure secp_verify is available

        # Setup puzzles
        secp_puzzle = construct_p2_delegated_secp(SECP_PK, DEFAULT_CONSTANTS.GENESIS_CHALLENGE, ENTROPY)
        secp_puzzlehash = secp_puzzle.get_tree_hash()
        p2_recovery_puzzle = construct_p2_recovery_puzzle(secp_puzzlehash, BLS_PK, TIMELOCK)
        p2_recovery_puzzlehash = p2_recovery_puzzle.get_tree_hash()
        vault_puzzle = construct_vault_puzzle(secp_puzzlehash, p2_recovery_puzzlehash)
        vault_puzzlehash = vault_puzzle.get_tree_hash()
        vault_merkle_tree = construct_vault_merkle_tree(secp_puzzlehash, p2_recovery_puzzlehash)

        await sim.farm_block(vault_puzzlehash)

        vault_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([vault_puzzlehash], include_spent_coins=False)
        )[0].coin

        # SECP SPEND
        amount = 10000
        secp_conditions = Program.to([[51, ACS_PH, amount], [51, vault_puzzlehash, vault_coin.amount - amount]])
        secp_delegated_puzzle = puzzle_for_conditions(secp_conditions)
        secp_delegated_solution = solution_for_conditions(secp_delegated_puzzle)
        secp_signature = SECP_SK.sign_deterministic(
            construct_secp_message(
                secp_delegated_puzzle.get_tree_hash(), vault_coin.name(), DEFAULT_CONSTANTS.GENESIS_CHALLENGE, ENTROPY
            )
        )

        secp_solution = Program.to(
            [
                secp_delegated_puzzle,
                secp_delegated_solution,
                secp_signature,
                vault_coin.name(),
            ]
        )

        proof = get_vault_proof(vault_merkle_tree, secp_puzzlehash)
        vault_solution_secp = Program.to([proof, secp_puzzle, secp_solution])
        vault_spendbundle = SpendBundle([make_spend(vault_coin, vault_puzzle, vault_solution_secp)], G2Element())

        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(vault_spendbundle)
        assert result[0] == MempoolInclusionStatus.SUCCESS
        await sim.farm_block()

        # RECOVERY SPEND
        vault_coin = (await client.get_coin_records_by_puzzle_hashes([vault_puzzlehash], include_spent_coins=False))[
            0
        ].coin

        recovery_conditions = Program.to([[51, ACS_PH, vault_coin.amount]])
        recovery_solution = Program.to([vault_coin.amount, recovery_conditions])
        recovery_proof = get_vault_proof(vault_merkle_tree, p2_recovery_puzzlehash)
        vault_solution_recovery = Program.to([recovery_proof, p2_recovery_puzzle, recovery_solution])
        vault_spendbundle = SpendBundle(
            [make_spend(vault_coin, vault_puzzle, vault_solution_recovery)],
            AugSchemeMPL.sign(
                BLS_SK,
                (
                    recovery_conditions.get_tree_hash()
                    + vault_coin.name()
                    + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
                ),
            ),
        )

        result = await client.push_tx(vault_spendbundle)
        assert result[0] == MempoolInclusionStatus.SUCCESS
        await sim.farm_block()

        recovery_finish_puzzle = construct_recovery_finish(TIMELOCK, recovery_conditions)
        recovery_finish_puzzlehash = recovery_finish_puzzle.get_tree_hash()
        recovery_puzzle = construct_vault_puzzle(secp_puzzlehash, recovery_finish_puzzlehash)
        recovery_puzzlehash = recovery_puzzle.get_tree_hash()
        recovery_merkle_tree = construct_vault_merkle_tree(secp_puzzlehash, recovery_finish_puzzlehash)

        recovery_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([recovery_puzzlehash], include_spent_coins=False)
        )[0].coin

        # Finish recovery
        proof = get_vault_proof(recovery_merkle_tree, recovery_finish_puzzlehash)
        recovery_finish_solution = Program.to([])
        recovery_solution = Program.to([proof, recovery_finish_puzzle, recovery_finish_solution])
        finish_spendbundle = SpendBundle([make_spend(recovery_coin, recovery_puzzle, recovery_solution)], G2Element())

        result = await client.push_tx(finish_spendbundle)
        assert result[1] == Err.ASSERT_SECONDS_RELATIVE_FAILED

        # Skip time
        sim.pass_time(TIMELOCK)
        await sim.farm_block()

        result = await client.push_tx(finish_spendbundle)
        assert result[0] == MempoolInclusionStatus.SUCCESS

        # Escape recovery
        # just farm a coin to the recovery puzhash
        await sim.farm_block(recovery_puzzlehash)
        recovery_coin = (
            await client.get_coin_records_by_puzzle_hashes([recovery_puzzlehash], include_spent_coins=False)
        )[0].coin

        proof = get_vault_proof(recovery_merkle_tree, secp_puzzlehash)
        secp_conditions = Program.to([[51, ACS_PH, recovery_coin.amount]])
        secp_delegated_puzzle = puzzle_for_conditions(secp_conditions)
        secp_delegated_solution = solution_for_conditions(secp_delegated_puzzle)
        secp_signature = SECP_SK.sign_deterministic(
            construct_secp_message(
                secp_delegated_puzzle.get_tree_hash(),
                recovery_coin.name(),
                DEFAULT_CONSTANTS.GENESIS_CHALLENGE,
                ENTROPY,
            )
        )
        secp_solution = Program.to(
            [
                secp_delegated_puzzle,
                secp_delegated_solution,
                secp_signature,
                recovery_coin.name(),
                DEFAULT_CONSTANTS.GENESIS_CHALLENGE,
            ]
        )

        recovery_solution = Program.to([proof, secp_puzzle, secp_solution])
        escape_spendbundle = SpendBundle([make_spend(recovery_coin, recovery_puzzle, recovery_solution)], G2Element())
        result = await client.push_tx(escape_spendbundle)
        assert result[0] == MempoolInclusionStatus.SUCCESS
