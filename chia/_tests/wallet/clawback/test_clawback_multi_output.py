from __future__ import annotations

import pytest
from chia_rs.sized_ints import uint32, uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.types.blockchain_format.program import Program
from chia.util.streamable import UInt32Range, VersionedBlob
from chia.wallet.conditions import Remark
from chia.wallet.puzzles.clawback.drivers import create_merkle_puzzle
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata, ClawbackVersion
from chia.wallet.util.wallet_types import CoinType, RemarkDataType


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1], "trusted": True, "reuse_puzhash": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_clawback_metadata_only_applies_to_matching_output(wallet_environments: WalletTestFramework) -> None:
    sender = wallet_environments.environments[0]
    recipient = wallet_environments.environments[1]

    async with recipient.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as scope:
        recipient_ph = await scope.get_puzzle_hash(recipient.wallet_state_manager)
    async with sender.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as scope:
        sender_ph = await scope.get_puzzle_hash(sender.wallet_state_manager)

    # Two clawback outputs with different timelocks; the remark only describes the first one
    described_ph = create_merkle_puzzle(uint64(3600), sender_ph, recipient_ph).get_tree_hash()
    other_ph = create_merkle_puzzle(uint64(10), sender_ph, recipient_ph).get_tree_hash()
    metadata = ClawbackMetadata(uint64(3600), sender_ph, recipient_ph)
    remark = Remark(
        Program.to([RemarkDataType.CLAWBACK, bytes(VersionedBlob(ClawbackVersion.V1.value, bytes(metadata)))])
    )

    async with sender.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as scope:
        await sender.xch_wallet.generate_signed_transaction(
            [uint64(200_000), uint64(300_000)],
            [described_ph, other_ph],
            scope,
            memos=[[recipient_ph], [recipient_ph]],
            extra_conditions=(remark,),
        )
    total = 500_000
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "unconfirmed_wallet_balance": -total,
                        "<=#spendable_balance": -total,
                        "<=#max_send_amount": -total,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -total,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    }
                },
            ),
            WalletStateTransition(pre_block_balance_updates={}, post_block_balance_updates={}),
        ]
    )

    records = await recipient.wallet_state_manager.coin_store.get_coin_records(
        coin_type=CoinType.CLAWBACK, spent_range=UInt32Range(stop=uint32(0))
    )
    assert [record.coin.puzzle_hash for record in records.records] == [described_ph]
    assert records.records[0].parsed_metadata() == metadata
