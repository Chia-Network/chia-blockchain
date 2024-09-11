from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.rpc.wallet_request_types import GetTransactionMemo
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import ReorgProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.types.peer_info import PeerInfo
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX
from chia.types.spend_bundle import estimate_fees
from chia.util.bech32m import encode_puzzle_hash
from chia.util.errors import Err
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.payment import Payment
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import CoinType
from chia.wallet.wallet_node import WalletNode, get_wallet_db_path


class TestWalletSimulator:
    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [10], "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_coinbase(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wsm = env.wallet_state_manager

        all_txs = await wsm.get_all_transactions(1)
        assert len(all_txs) == 20

        pool_rewards = 0
        farm_rewards = 0

        for tx in all_txs:
            if TransactionType(tx.type) == TransactionType.COINBASE_REWARD:
                pool_rewards += 1
            elif TransactionType(tx.type) == TransactionType.FEE_REWARD:
                farm_rewards += 1

        assert pool_rewards == 10
        assert farm_rewards == 10

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [1]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_make_transaction(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wallet = env.xch_wallet

        tx_amount = 10

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                bytes32([0] * 32),
                action_scope,
                uint64(0),
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,
                            ">=#max_send_amount": 1,
                            "<=#pending_change": 1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                )
            ]
        )

        # Test match_hinted_coin
        async with wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=False
        ) as action_scope:
            selected_coin = list(await wallet.select_coins(uint64(0), action_scope))[0]
        assert await wallet.match_hinted_coin(selected_coin, selected_coin.puzzle_hash)

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [1], "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_reuse_address(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wallet = env.xch_wallet

        tx_amount = 10

        async with wallet.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG.override(reuse_puzhash=True), push=True
        ) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                bytes32([0] * 32),
                action_scope,
                uint64(0),
            )
        [tx] = action_scope.side_effects.transactions
        assert tx.spend_bundle is not None
        assert len(tx.spend_bundle.coin_spends) == 1
        new_puzhash = [c.puzzle_hash.hex() for c in tx.additions]
        assert tx.spend_bundle.coin_spends[0].coin.puzzle_hash.hex() in new_puzhash
        [tx] = await wallet.wallet_state_manager.add_pending_transactions([tx])

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,
                            ">=#max_send_amount": 1,
                            "<=#pending_change": 1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                )
            ]
        )

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [2, 1], "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.parametrize("number_of_coins", [1, 3])
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_clawback_claim_auto(
        self, wallet_environments: WalletTestFramework, number_of_coins: int
    ) -> None:
        env = wallet_environments.environments[0]
        env_1 = wallet_environments.environments[1]
        wallet = env.xch_wallet
        wallet_1 = env_1.xch_wallet
        wsm = env.wallet_state_manager
        wsm_1 = env_1.wallet_state_manager

        tx_amount = 500
        normal_puzhash = await wallet_1.get_new_puzzlehash()

        # Transfer to normal wallet
        for _ in range(0, number_of_coins):
            async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
                await wallet.generate_signed_transaction(
                    uint64(tx_amount),
                    normal_puzhash,
                    action_scope,
                    uint64(0),
                    puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 10}],
                )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount * number_of_coins,
                            "<=#spendable_balance": -1 * tx_amount * number_of_coins,
                            "<=#max_send_amount": -1 * tx_amount * number_of_coins,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": number_of_coins,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount * number_of_coins,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -number_of_coins,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        await time_out_assert(20, wsm.coin_store.count_small_unspent, number_of_coins, tx_amount * 2, CoinType.CLAWBACK)
        await time_out_assert(
            20, wsm_1.coin_store.count_small_unspent, number_of_coins, tx_amount * 2, CoinType.CLAWBACK
        )

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                normal_puzhash,
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 10}],
            )
        [tx_bad] = action_scope.side_effects.transactions

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Change one coin to test missing metadata case
        clawback_coin_id = tx_bad.additions[0].name()
        coin_record = await wsm_1.coin_store.get_coin_record(clawback_coin_id)
        assert coin_record is not None
        await wsm_1.coin_store.add_coin_record(dataclasses.replace(coin_record, metadata=None))
        # Claim merkle coin
        env_1.node.set_auto_claim(AutoClaimSettings(enabled=True, batch_size=uint16(2)))
        # Trigger auto claim
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    # After auto claim is set, the next block will trigger submission of clawback claims
                    post_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": tx_amount * number_of_coins,
                            "pending_change": tx_amount
                            * number_of_coins,  # This is a little weird but I think intentional and correct
                            "pending_coin_removal_count": number_of_coins,
                        }
                    },
                ),
            ]
        )
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount * number_of_coins,
                            "spendable_balance": tx_amount * number_of_coins,
                            "max_send_amount": tx_amount * number_of_coins,
                            "unspent_coin_count": number_of_coins,
                            "pending_change": -tx_amount * number_of_coins,
                            "pending_coin_removal_count": -1 * number_of_coins,
                        }
                    },
                ),
            ]
        )
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, tx_amount * 2, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_1.coin_store.count_small_unspent, 1, tx_amount * 2, CoinType.CLAWBACK)

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [1, 1], "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_clawback_clawback(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        env_2 = wallet_environments.environments[1]
        wsm = env.wallet_state_manager
        wsm_2 = env_2.wallet_state_manager
        wallet = env.xch_wallet
        wallet_1 = env_2.xch_wallet
        api_0 = env.rpc_api
        api_1 = env_2.rpc_api

        tx_amount = 500
        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                normal_puzhash,
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 500}],
                memos=[b"Test"],
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Check merkle coins
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        txs = await api_0.get_transactions(
            dict(type_filter={"values": [TransactionType.INCOMING_CLAWBACK_SEND], "mode": 1}, wallet_id=1)
        )
        # clawback merkle coin
        [tx] = action_scope.side_effects.transactions
        merkle_coin = tx.additions[0] if tx.additions[0].amount == tx_amount else tx.additions[1]
        interested_coins = await wsm_2.interested_store.get_interested_coin_ids()
        assert merkle_coin.name() in set(interested_coins)
        assert len(txs["transactions"]) == 1
        assert not txs["transactions"][0]["confirmed"]
        assert txs["transactions"][0]["metadata"]["recipient_puzzle_hash"][2:] == normal_puzhash.hex()
        assert txs["transactions"][0]["metadata"]["coin_id"] == merkle_coin.name().hex()
        with pytest.raises(ValueError):
            await api_0.spend_clawback_coins({})

        test_fee = 10
        resp = await api_0.spend_clawback_coins(
            {"coin_ids": [normal_puzhash.hex(), merkle_coin.name().hex()], "fee": test_fee}
        )
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": tx_amount - test_fee,
                            "<=#spendable_balance": -1,
                            "<=#max_send_amount": -1,
                            ">=#pending_change": 1,
                            "pending_coin_removal_count": 2,  # 1 for fee, one for clawback
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount - test_fee,
                            ">=#spendable_balance": 1,
                            ">=#max_send_amount": 1,
                            "<=#pending_change": -1,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -2,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        await time_out_assert(20, wsm.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        txs = await api_0.get_transactions(
            dict(
                type_filter={
                    "values": [TransactionType.INCOMING_CLAWBACK_SEND.value, TransactionType.OUTGOING_CLAWBACK.value],
                    "mode": 1,
                },
                wallet_id=1,
            )
        )
        assert len(txs["transactions"]) == 2
        assert txs["transactions"][0]["confirmed"]
        assert txs["transactions"][1]["confirmed"]

        txs = await api_1.get_transactions(
            dict(
                type_filter={
                    "values": [
                        TransactionType.INCOMING_CLAWBACK_RECEIVE.value,
                        TransactionType.OUTGOING_CLAWBACK.value,
                    ],
                    "mode": 1,
                },
                wallet_id=1,
            )
        )
        assert len(txs["transactions"]) == 1
        assert txs["transactions"][0]["confirmed"]
        interested_coins = await wsm_2.interested_store.get_interested_coin_ids()
        assert merkle_coin.name() not in set(interested_coins)

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [1], "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_clawback_sent_self(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wsm = env.wallet_state_manager
        wallet = env.xch_wallet
        api_0 = env.rpc_api

        tx_amount = 500
        normal_puzhash = await wallet.get_new_puzzlehash()
        # Transfer to normal wallet
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                normal_puzhash,
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
                memos=[b"Test"],
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Check merkle coins
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        # Claim merkle coin
        [tx] = action_scope.side_effects.transactions
        merkle_coin = tx.additions[0] if tx.additions[0].amount == tx_amount else tx.additions[1]
        test_fee = 10
        resp = await api_0.spend_clawback_coins(
            {"coin_ids": [merkle_coin.name().hex(), normal_puzhash.hex()], "fee": test_fee}
        )
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1
        # Wait mempool update
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": tx_amount - test_fee,
                            "<=#spendable_balance": -1,
                            "<=#max_send_amount": -1,
                            ">=#pending_change": 1,
                            "pending_coin_removal_count": 2,  # 1 for fee, one for clawback
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount - test_fee,
                            ">=#spendable_balance": 1,
                            ">=#max_send_amount": 1,
                            "<=#pending_change": -1,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -2,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)

        txs = await api_0.get_transactions(
            dict(
                type_filter={
                    "values": [TransactionType.INCOMING_CLAWBACK_SEND.value, TransactionType.OUTGOING_CLAWBACK.value],
                    "mode": 1,
                },
                wallet_id=1,
            )
        )
        assert len(txs["transactions"]) == 2
        assert txs["transactions"][0]["confirmed"]
        assert txs["transactions"][1]["confirmed"]
        assert txs["transactions"][0]["memos"] != txs["transactions"][1]["memos"]
        assert list(txs["transactions"][0]["memos"].values())[0] == b"Test".hex()

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [1, 1], "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_clawback_claim_manual(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        env_2 = wallet_environments.environments[1]
        wsm = env.wallet_state_manager
        wsm_2 = env_2.wallet_state_manager
        wallet = env.xch_wallet
        wallet_1 = env_2.xch_wallet
        api_0 = env.rpc_api
        api_1 = env_2.rpc_api

        tx_amount = 500
        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                normal_puzhash,
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Check merkle coins
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)

        # Farm a block to pass timelock
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Claim merkle coin
        [tx] = action_scope.side_effects.transactions
        merkle_coin = tx.additions[0] if tx.additions[0].amount == tx_amount else tx.additions[1]
        test_fee = 10
        resp = await api_1.spend_clawback_coins(
            {"coin_ids": [merkle_coin.name().hex(), normal_puzhash.hex()], "fee": test_fee}
        )
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": tx_amount - test_fee,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 2,  # 1 for fee, 1 for clawback
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount - test_fee,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -2,
                        }
                    },
                ),
            ]
        )

        await time_out_assert(20, wsm.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)

        txs = await api_0.get_transactions(
            dict(
                type_filter={
                    "values": [
                        TransactionType.INCOMING_CLAWBACK_SEND.value,
                    ],
                    "mode": 1,
                },
                wallet_id=1,
            )
        )
        assert len(txs["transactions"]) == 1
        assert txs["transactions"][0]["confirmed"]

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [1, 1], "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_clawback_reorg(self, wallet_environments: WalletTestFramework) -> None:
        full_node_api = wallet_environments.full_node
        env = wallet_environments.environments[0]
        env_2 = wallet_environments.environments[1]
        wsm = env.wallet_state_manager
        wsm_2 = env_2.wallet_state_manager
        wallet = env.xch_wallet
        wallet_1 = env_2.xch_wallet

        tx_amount = 500
        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                normal_puzhash,
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Check merkle coins
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        # Reorg before claim
        # Test Reorg mint
        height = full_node_api.full_node.blockchain.get_peak_height()
        assert height is not None
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(height - 2), uint32(height + 1), bytes32([0] * 32), None)
        )

        await time_out_assert(20, wsm.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,  # confirmed balance comes back
                            # clawback transaction is now outstanding
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)

        # Claim merkle coin
        env_2.node.set_auto_claim(AutoClaimSettings(enabled=True))
        # clawback merkle coin
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    # After auto claim is set, the next block will trigger submission of clawback claims
                    post_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": tx_amount,
                            "pending_change": tx_amount,  # This is a little weird but I think intentional and correct
                            "pending_coin_removal_count": 1,
                        }
                    },
                ),
            ]
        )
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                            "pending_change": -1 * tx_amount,
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
            ]
        )
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        # Reorg after claim
        height = full_node_api.full_node.blockchain.get_peak_height()
        assert height is not None
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32([0] * 32), None)
        )

        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            "spendable_balance": -1 * tx_amount,
                            "max_send_amount": -1 * tx_amount,
                            "unspent_coin_count": -1,
                            "pending_change": tx_amount,
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                            "pending_change": -1 * tx_amount,
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
            ]
        )

        await time_out_assert(20, wsm.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [1], "trusted": True, "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_get_clawback_coins(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wsm = env.wallet_state_manager
        wallet = env.xch_wallet

        tx_amount = 500
        # Transfer to normal wallet
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                bytes32([0] * 32),
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 500}],
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Check merkle coins
        await time_out_assert(20, wsm.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        # clawback merkle coin
        [tx] = action_scope.side_effects.transactions
        merkle_coin = tx.additions[0] if tx.additions[0].amount == tx_amount else tx.additions[1]
        resp = await env.rpc_api.get_coin_records({"wallet_id": 1, "coin_type": 1})
        assert len(resp["coin_records"]) == 1
        assert resp["coin_records"][0]["id"][2:] == merkle_coin.name().hex()

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [1, 1], "reuse_puzhash": False}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_clawback_resync(self, self_hostname: str, wallet_environments: WalletTestFramework) -> None:
        full_node_api = wallet_environments.full_node
        env_1 = wallet_environments.environments[0]
        env_2 = wallet_environments.environments[1]
        wsm_1 = env_1.wallet_state_manager
        wsm_2 = env_2.wallet_state_manager
        wallet_1 = env_1.xch_wallet
        wallet_2 = env_2.xch_wallet
        api_1 = env_1.rpc_api

        wallet_1_puzhash = await wallet_1.get_new_puzzlehash()
        wallet_2_puzhash = await wallet_2.get_new_puzzlehash()

        tx_amount = 500
        # Transfer to normal wallet
        async with wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_1.generate_signed_transaction(
                uint64(tx_amount),
                wallet_2_puzhash,
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
            )

        [tx1] = action_scope.side_effects.transactions
        clawback_coin_id_1 = tx1.additions[0].name()
        assert tx1.spend_bundle is not None

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Check merkle coins
        await time_out_assert(20, wsm_1.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)

        tx_amount2 = 700
        async with wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_1.generate_signed_transaction(
                uint64(tx_amount2),
                wallet_1_puzhash,
                action_scope,
                uint64(0),
                puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
            )
        [tx2] = action_scope.side_effects.transactions
        clawback_coin_id_2 = tx2.additions[0].name()
        assert tx2.spend_bundle is not None

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount2,
                            "<=#spendable_balance": -1 * tx_amount2,
                            "<=#max_send_amount": -1 * tx_amount2,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount2,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        # Check merkle coins
        await time_out_assert(20, wsm_1.coin_store.count_small_unspent, 2, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK)
        # clawback merkle coin
        resp = await api_1.spend_clawback_coins({"coin_ids": [clawback_coin_id_1.hex()], "fee": 0})
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1
        resp = await api_1.spend_clawback_coins({"coin_ids": [clawback_coin_id_2.hex()], "fee": 0})
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": tx_amount + tx_amount2,
                            "pending_change": tx_amount + tx_amount2,
                            "pending_coin_removal_count": 2,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount + tx_amount2,
                            "max_send_amount": tx_amount + tx_amount2,
                            "spendable_balance": tx_amount + tx_amount2,
                            "pending_change": -1 * (tx_amount + tx_amount2),
                            "unspent_coin_count": 2,
                            "pending_coin_removal_count": -2,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        await time_out_assert(20, wsm_1.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)
        await time_out_assert(20, wsm_2.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK)

        before_txs: Dict[str, Dict[TransactionType, int]] = {"sender": {}, "recipient": {}}
        before_txs["sender"][TransactionType.INCOMING_CLAWBACK_SEND] = (
            await wsm_1.tx_store.get_transaction_count_for_wallet(
                1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_SEND])
            )
        )
        before_txs["sender"][TransactionType.OUTGOING_CLAWBACK] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.OUTGOING_CLAWBACK])
        )
        before_txs["sender"][TransactionType.OUTGOING_TX] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.OUTGOING_TX])
        )
        before_txs["sender"][TransactionType.INCOMING_TX] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_TX])
        )
        before_txs["sender"][TransactionType.COINBASE_REWARD] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.COINBASE_REWARD])
        )
        before_txs["recipient"][TransactionType.INCOMING_CLAWBACK_RECEIVE] = (
            await wsm_2.tx_store.get_transaction_count_for_wallet(
                1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_RECEIVE])
            )
        )
        # Resync start
        env_1.node._close()
        await env_1.node._await_closed()
        env_2.node._close()
        await env_2.node._await_closed()
        env_1.node.config["database_path"] = "wallet/db/blockchain_wallet_v2_test1_CHALLENGE_KEY.sqlite"
        env_2.node.config["database_path"] = "wallet/db/blockchain_wallet_v2_test2_CHALLENGE_KEY.sqlite"

        # use second node to start the same wallet, reusing config and db
        await env_1.node._start()
        await env_1.peer_server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)
        await env_2.node._start()
        await env_2.peer_server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(),
                WalletStateTransition(),
            ]
        )

        wsm_1 = env_1.node.wallet_state_manager
        wsm_2 = env_2.node.wallet_state_manager

        after_txs: Dict[str, Dict[TransactionType, int]] = {"sender": {}, "recipient": {}}
        after_txs["sender"][TransactionType.INCOMING_CLAWBACK_SEND] = (
            await wsm_1.tx_store.get_transaction_count_for_wallet(
                1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_SEND])
            )
        )
        after_txs["sender"][TransactionType.OUTGOING_CLAWBACK] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.OUTGOING_CLAWBACK])
        )
        after_txs["sender"][TransactionType.OUTGOING_TX] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.OUTGOING_TX])
        )
        after_txs["sender"][TransactionType.INCOMING_TX] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_TX])
        )
        after_txs["sender"][TransactionType.COINBASE_REWARD] = await wsm_1.tx_store.get_transaction_count_for_wallet(
            1, type_filter=TransactionTypeFilter.include([TransactionType.COINBASE_REWARD])
        )
        after_txs["recipient"][TransactionType.INCOMING_CLAWBACK_RECEIVE] = (
            await wsm_2.tx_store.get_transaction_count_for_wallet(
                1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_RECEIVE])
            )
        )
        # Check clawback
        clawback_tx_1 = await wsm_1.tx_store.get_transaction_record(clawback_coin_id_1)
        clawback_tx_2 = await wsm_1.tx_store.get_transaction_record(clawback_coin_id_2)
        assert clawback_tx_1 is not None
        assert clawback_tx_1.confirmed
        assert clawback_tx_2 is not None
        assert clawback_tx_2.confirmed
        outgoing_clawback_txs = await wsm_1.tx_store.get_transactions_between(
            1, 0, 100, type_filter=TransactionTypeFilter.include([TransactionType.OUTGOING_CLAWBACK])
        )
        assert len(outgoing_clawback_txs) == 2
        assert outgoing_clawback_txs[0].confirmed
        assert outgoing_clawback_txs[1].confirmed

        # transactions should be the same

        assert (
            before_txs["sender"][TransactionType.OUTGOING_CLAWBACK]
            == after_txs["sender"][TransactionType.OUTGOING_CLAWBACK]
        )
        assert before_txs["sender"] == after_txs["sender"]
        assert before_txs["recipient"] == after_txs["recipient"]

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [3]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_coinbase_reorg(self, wallet_environments: WalletTestFramework) -> None:
        full_node_api = wallet_environments.full_node
        env = wallet_environments.environments[0]
        wallet = env.xch_wallet

        peak = full_node_api.full_node.blockchain.get_peak()
        assert peak is not None
        permanent_height = peak.height  # The height of the blocks we will not reorg

        extra_blocks = 2
        await full_node_api.farm_blocks_to_wallet(count=extra_blocks, wallet=wallet)
        await full_node_api.wait_for_wallet_synced(wallet_node=env.node, timeout=5)
        await env.change_balances(
            {
                1: {
                    "confirmed_wallet_balance": 2_000_000_000_000 * extra_blocks,
                    "unconfirmed_wallet_balance": 2_000_000_000_000 * extra_blocks,
                    "max_send_amount": 2_000_000_000_000 * extra_blocks,
                    "spendable_balance": 2_000_000_000_000 * extra_blocks,
                    "unspent_coin_count": 4,
                }
            }
        )

        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(
                uint32(permanent_height), uint32(permanent_height + extra_blocks + 6), bytes32(32 * b"0"), None
            )
        )

        await full_node_api.wait_for_wallet_synced(wallet_node=env.node, timeout=5)

        await env.change_balances(
            {
                1: {
                    "confirmed_wallet_balance": -2_000_000_000_000 * extra_blocks,
                    "unconfirmed_wallet_balance": -2_000_000_000_000 * extra_blocks,
                    "max_send_amount": -2_000_000_000_000 * extra_blocks,
                    "spendable_balance": -2_000_000_000_000 * extra_blocks,
                    "unspent_coin_count": -4,
                }
            }
        )

    @pytest.mark.parametrize("trusted", [True, False])
    @pytest.mark.anyio
    async def test_wallet_send_to_three_peers(
        self,
        three_sim_two_wallets: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 10
        full_nodes, wallets, _ = three_sim_two_wallets

        wallet_0, wallet_server_0 = wallets[0]

        full_node_api_0 = full_nodes[0]
        full_node_api_1 = full_nodes[1]
        full_node_api_2 = full_nodes[2]

        full_node_0 = full_node_api_0.full_node
        full_node_1 = full_node_api_1.full_node
        full_node_2 = full_node_api_2.full_node

        server_0 = full_node_0.server
        server_1 = full_node_1.server
        server_2 = full_node_2.server

        if trusted:
            wallet_0.config["trusted_peers"] = {
                server_0.node_id.hex(): server_0.node_id.hex(),
                server_1.node_id.hex(): server_1.node_id.hex(),
                server_2.node_id.hex(): server_2.node_id.hex(),
            }

        else:
            wallet_0.config["trusted_peers"] = {}

        # wallet0 <-> sever0
        await wallet_server_0.start_client(PeerInfo(self_hostname, server_0.get_port()), None)

        await full_node_api_0.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0.wallet_state_manager.main_wallet)

        all_blocks = await full_node_api_0.get_all_full_blocks()

        for block in all_blocks:
            await full_node_1.add_block(block)
            await full_node_2.add_block(block)

        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(
                uint64(10),
                bytes32(32 * b"0"),
                action_scope,
                uint64(0),
            )
        await full_node_api_0.wait_transaction_records_entered_mempool(records=action_scope.side_effects.transactions)

        # wallet0 <-> sever1
        await wallet_server_0.start_client(PeerInfo(self_hostname, server_1.get_port()), wallet_0.on_connect)
        await full_node_api_1.wait_transaction_records_entered_mempool(records=action_scope.side_effects.transactions)

        # wallet0 <-> sever2
        await wallet_server_0.start_client(PeerInfo(self_hostname, server_2.get_port()), wallet_0.on_connect)
        await full_node_api_2.wait_transaction_records_entered_mempool(records=action_scope.side_effects.transactions)

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [1, 1]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_make_transaction_hop(self, wallet_environments: WalletTestFramework) -> None:
        env_0 = wallet_environments.environments[0]
        env_1 = wallet_environments.environments[1]
        wallet_0 = env_0.xch_wallet
        wallet_1 = env_1.xch_wallet

        tx_amount = 10
        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_0.generate_signed_transaction(
                uint64(tx_amount),
                await wallet_1.get_puzzle_hash(False),
                action_scope,
                uint64(0),
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "unconfirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                        }
                    },
                ),
            ]
        )

        tx_amount = 5
        async with wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_1.generate_signed_transaction(
                uint64(tx_amount), await wallet_0.get_puzzle_hash(False), action_scope, uint64(0)
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "unconfirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
            ]
        )

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [1, 1]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_make_transaction_with_fee(self, wallet_environments: WalletTestFramework) -> None:
        env_0 = wallet_environments.environments[0]
        env_1 = wallet_environments.environments[1]
        wallet_0 = env_0.xch_wallet
        wallet_1 = env_1.xch_wallet

        tx_amount = 1_750_000_000_000  # ensures we grab both coins
        tx_fee = 10
        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_0.generate_signed_transaction(
                uint64(tx_amount),
                await wallet_1.get_new_puzzlehash(),
                action_scope,
                uint64(tx_fee),
            )
        [tx] = action_scope.side_effects.transactions
        assert tx.spend_bundle is not None

        fees = estimate_fees(tx.spend_bundle)
        assert fees == tx_fee

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount - tx_fee,
                            "<=#spendable_balance": -1 * tx_amount - tx_fee,
                            "<=#max_send_amount": -1 * tx_amount - tx_fee,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 2,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount - tx_fee,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -2,
                            "unspent_coin_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "unconfirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                        }
                    },
                ),
            ]
        )

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [1, 1]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_make_transaction_with_memo(self, wallet_environments: WalletTestFramework) -> None:
        env_0 = wallet_environments.environments[0]
        env_1 = wallet_environments.environments[1]
        wallet_0 = env_0.xch_wallet
        wallet_1 = env_1.xch_wallet

        tx_amount = 1_750_000_000_000  # ensures we grab both coins
        tx_fee = 10
        ph_2 = await wallet_1.get_new_puzzlehash()
        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_0.generate_signed_transaction(
                uint64(tx_amount), ph_2, action_scope, uint64(tx_fee), memos=[ph_2]
            )
        [tx] = action_scope.side_effects.transactions
        assert tx.spend_bundle is not None

        fees = estimate_fees(tx.spend_bundle)
        assert fees == tx_fee

        memos = await env_0.rpc_client.get_transaction_memo(GetTransactionMemo(transaction_id=tx.name))
        assert len(memos.coins_with_memos) == 1
        assert memos.coins_with_memos[0].memos[0] == ph_2

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount - tx_fee,
                            "<=#spendable_balance": -1 * tx_amount - tx_fee,
                            "<=#max_send_amount": -1 * tx_amount - tx_fee,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 2,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount - tx_fee,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -2,
                            "unspent_coin_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "unconfirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                        }
                    },
                ),
            ]
        )

        tx_id = None
        for coin in tx.additions:
            if coin.amount == tx_amount:
                tx_id = coin.name()
        assert tx_id is not None
        memos = await env_1.rpc_client.get_transaction_memo(GetTransactionMemo(transaction_id=tx_id))
        assert len(memos.coins_with_memos) == 1
        assert memos.coins_with_memos[0].memos[0] == ph_2
        # test json serialization
        assert memos.to_json_dict() == {
            tx_id.hex(): {memos.coins_with_memos[0].coin_id.hex(): [memos.coins_with_memos[0].memos[0].hex()]}
        }

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [1], "trusted": True, "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_create_hit_max_send_amount(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wallet = env.xch_wallet

        ph = await wallet.get_puzzle_hash(False)
        primaries = [Payment(ph, uint64(1000000000 + i)) for i in range(int(wallet.max_send_quantity) + 1)]
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(uint64(1), ph, action_scope, uint64(0), primaries=primaries)

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            # tx sent to ourselves
                            "unconfirmed_wallet_balance": 0,
                            "<=#spendable_balance": 0,
                            "<=#max_send_amount": 0,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": 0,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                            "unspent_coin_count": len(primaries) + 1,
                        }
                    },
                ),
            ]
        )

        max_sent_amount = await wallet.get_max_send_amount()
        assert max_sent_amount < (await wallet.get_spendable_balance())

        # 1) Generate transaction that is under the limit
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(max_sent_amount - 1),
                ph,
                action_scope,
                uint64(0),
            )

        assert action_scope.side_effects.transactions[0].amount == uint64(max_sent_amount - 1)

        # 2) Generate transaction that is equal to limit
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(max_sent_amount),
                ph,
                action_scope,
                uint64(0),
            )

        assert action_scope.side_effects.transactions[0].amount == uint64(max_sent_amount)

        # 3) Generate transaction that is greater than limit
        with pytest.raises(
            ValueError,
            match=f"Transaction for {max_sent_amount + 1} is greater than max spendable balance in a block of "
            f"{max_sent_amount}. There may be other transactions pending or our minimum coin amount is too high.",
        ):
            async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
                await wallet.generate_signed_transaction(
                    uint64(max_sent_amount + 1),
                    ph,
                    action_scope,
                    uint64(0),
                )

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [2], "trusted": True, "reuse_puzhash": True}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_prevent_fee_theft(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wallet = env.xch_wallet

        tx_amount = 1_750_000_000_000
        tx_fee = 2_000_000_000_000
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount),
                bytes32([0] * 32),
                action_scope,
                uint64(tx_fee),
            )
        [tx] = action_scope.side_effects.transactions
        assert tx.spend_bundle is not None

        stolen_cs: Optional[CoinSpend] = None
        # extract coin_spend from generated spend_bundle
        for cs in tx.spend_bundle.coin_spends:
            if compute_additions(cs) == []:
                stolen_cs = cs

        assert stolen_cs is not None

        # get a legit signature
        stolen_sb, _ = await wallet.wallet_state_manager.sign_bundle([stolen_cs])
        name = stolen_sb.name()
        stolen_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(0),
            to_puzzle_hash=bytes32(32 * b"0"),
            amount=uint64(0),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=stolen_sb,
            additions=[],
            removals=[],
            wallet_id=wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=name,
            memos=[],
            valid_times=ConditionValidTimes(),
        )
        [stolen_tx] = await wallet.wallet_state_manager.add_pending_transactions([stolen_tx])

        async def transaction_has_failed(tx_id: bytes32) -> bool:
            tx = await wallet.wallet_state_manager.tx_store.get_transaction_record(tx_id)
            assert tx is not None
            return any(error_str == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED.name for _, _, error_str in tx.sent_to)

        await time_out_assert(10, transaction_has_failed, True, stolen_tx.name)

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 2, "blocks_needed": [4, 1]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_tx_reorg(self, wallet_environments: WalletTestFramework) -> None:
        full_node_api = wallet_environments.full_node
        env = wallet_environments.environments[0]
        env_2 = wallet_environments.environments[1]
        wsm = env.wallet_state_manager
        wallet = env.xch_wallet
        wallet_2 = env_2.xch_wallet

        # Ensure that we use a coin that we will not reorg out
        tx_amount = 1000
        async with wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=False
        ) as action_scope:
            coins = await wallet.select_coins(amount=uint64(tx_amount), action_scope=action_scope)
        coin = next(iter(coins))

        reorg_height = full_node_api.full_node.blockchain.get_peak_height()
        assert reorg_height is not None
        await full_node_api.farm_blocks_to_puzzlehash(count=3)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction(
                uint64(tx_amount), await wallet_2.get_puzzle_hash(False), action_scope, coins={coin}
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "<=#spendable_balance": -1 * tx_amount,
                            "<=#max_send_amount": -1 * tx_amount,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": 1,  # any amount increase
                            ">=#max_send_amount": 1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "unconfirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                        }
                    },
                ),
            ]
        )

        peak = full_node_api.full_node.blockchain.get_peak()
        assert peak is not None
        peak_height = peak.height
        assert peak_height is not None

        target_height_after_reorg = peak_height + 3
        # Perform a reorg, which will revert the transaction in the full node and wallet, and cause wallet to resubmit
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(reorg_height - 1), uint32(target_height_after_reorg), bytes32(32 * b"0"), None)
        )

        await time_out_assert(20, full_node_api.full_node.blockchain.get_peak_height, target_height_after_reorg)

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "unconfirmed_wallet_balance": 0,
                            "<=#spendable_balance": -1,  # any amount decrease
                            "<=#max_send_amount": -1,  # any amount decrease
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            ">=#spendable_balance": -1,  # any amount increase
                            ">=#max_send_amount": -1,  # any amount increase
                            "<=#pending_change": -1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * tx_amount,
                            "unconfirmed_wallet_balance": -1 * tx_amount,
                            "spendable_balance": -1 * tx_amount,
                            "max_send_amount": -1 * tx_amount,
                            "unspent_coin_count": -1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": tx_amount,
                            "unconfirmed_wallet_balance": tx_amount,
                            "spendable_balance": tx_amount,
                            "max_send_amount": tx_amount,
                            "unspent_coin_count": 1,
                        }
                    },
                ),
            ]
        )

        unconfirmed = await wsm.tx_store.get_unconfirmed_for_wallet(int(wallet.id()))
        assert len(unconfirmed) == 0
        [tx] = action_scope.side_effects.transactions
        tx_record = await wsm.tx_store.get_transaction_record(tx.name)
        assert tx_record is not None
        removed = tx_record.removals[0]
        added = tx_record.additions[0]
        added_1 = tx_record.additions[1]
        wallet_coin_record_rem = await wsm.coin_store.get_coin_record(removed.name())
        assert wallet_coin_record_rem is not None
        assert wallet_coin_record_rem.spent

        coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(removed.name())
        assert coin_record_full_node is not None
        assert coin_record_full_node.spent
        add_1_coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(added.name())
        assert add_1_coin_record_full_node is not None
        assert add_1_coin_record_full_node.confirmed_block_index > 0
        add_2_coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(added_1.name())
        assert add_2_coin_record_full_node is not None
        assert add_2_coin_record_full_node.confirmed_block_index > 0

    @pytest.mark.parametrize(
        "wallet_environments",
        [
            {
                "num_environments": 1,
                "blocks_needed": [1],
                "trusted": True,
                "reuse_puzhash": False,
                "config_overrides": {"initial_num_public_keys": 100},
            }
        ],
        indirect=True,
    )
    @pytest.mark.anyio
    async def test_address_sliding_window(self, wallet_environments: WalletTestFramework) -> None:
        full_node_api = wallet_environments.full_node
        env = wallet_environments.environments[0]
        wallet = env.xch_wallet

        peak = full_node_api.full_node.blockchain.get_peak_height()
        assert peak is not None

        puzzle_hashes = []
        for i in range(211):
            pubkey = master_sk_to_wallet_sk(wallet.wallet_state_manager.get_master_private_key(), uint32(i)).get_g1()
            puzzle: Program = wallet.puzzle_for_pk(pubkey)
            puzzle_hash: bytes32 = puzzle.get_tree_hash()
            puzzle_hashes.append(puzzle_hash)

        await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=puzzle_hashes[0])
        await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=puzzle_hashes[210])
        await full_node_api.farm_blocks_to_puzzlehash(
            count=1,
            farm_to=puzzle_hashes[114],
            guarantee_transaction_blocks=True,
        )

        await full_node_api.wait_for_wallet_synced(env.node, peak_height=uint32(peak + 3))
        await env.change_balances(
            {
                1: {
                    "confirmed_wallet_balance": 2_000_000_000_000,
                    "unconfirmed_wallet_balance": 2_000_000_000_000,
                    "spendable_balance": 2_000_000_000_000,
                    "max_send_amount": 2_000_000_000_000,
                    "unspent_coin_count": 2,
                }
            }
        )

        await full_node_api.farm_blocks_to_puzzlehash(
            count=1,
            farm_to=puzzle_hashes[50],
            guarantee_transaction_blocks=True,
        )
        await full_node_api.farm_blocks_to_puzzlehash(
            count=1,
            guarantee_transaction_blocks=True,
        )

        await full_node_api.wait_for_wallet_synced(env.node, peak_height=uint32(peak + 5))
        await env.change_balances(
            {
                1: {
                    "confirmed_wallet_balance": 6_000_000_000_000,
                    "unconfirmed_wallet_balance": 6_000_000_000_000,
                    "spendable_balance": 6_000_000_000_000,
                    "max_send_amount": 6_000_000_000_000,
                    "unspent_coin_count": 6,
                }
            }
        )

        await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=puzzle_hashes[113])
        await full_node_api.farm_blocks_to_puzzlehash(
            count=1,
            farm_to=puzzle_hashes[209],
            guarantee_transaction_blocks=True,
        )
        await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)

        await full_node_api.wait_for_wallet_synced(env.node, peak_height=uint32(peak + 8))
        await env.change_balances(
            {
                1: {
                    "confirmed_wallet_balance": 4_000_000_000_000,
                    "unconfirmed_wallet_balance": 4_000_000_000_000,
                    "spendable_balance": 4_000_000_000_000,
                    "max_send_amount": 4_000_000_000_000,
                    "unspent_coin_count": 4,
                }
            }
        )

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [1]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_sign_message(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        api_0 = env.rpc_api

        # Test general string
        message = "Hello World"
        ph = await env.xch_wallet.get_puzzle_hash(False)
        response = await api_0.sign_message_by_address({"address": encode_puzzle_hash(ph, "xch"), "message": message})
        puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            puzzle.get_tree_hash(),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )
        # Test hex string
        message = "0123456789ABCDEF"
        response = await api_0.sign_message_by_address(
            {"address": encode_puzzle_hash(ph, "xch"), "message": message, "is_hex": True}
        )
        puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            puzzle.get_tree_hash(),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )
        # Test informal input
        message = "0123456789ABCDEF"
        response = await api_0.sign_message_by_address(
            {"address": encode_puzzle_hash(ph, "xch"), "message": message, "is_hex": "true", "safe_mode": "true"}
        )
        puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            puzzle.get_tree_hash(),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )
        # Test BLS sign string
        message = "Hello World"
        response = await api_0.sign_message_by_address(
            {"address": encode_puzzle_hash(ph, "xch"), "message": message, "is_hex": False, "safe_mode": False}
        )

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            bytes(message, "utf-8"),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )
        # Test BLS sign hex
        message = "0123456789ABCDEF"
        response = await api_0.sign_message_by_address(
            {"address": encode_puzzle_hash(ph, "xch"), "message": message, "is_hex": True, "safe_mode": False}
        )

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            bytes.fromhex(message),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )

    @pytest.mark.parametrize(
        "wallet_environments",
        [{"num_environments": 1, "blocks_needed": [2]}],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    @pytest.mark.anyio
    async def test_wallet_transaction_options(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        wallet = env.xch_wallet

        AMOUNT_TO_SEND = 4000000000000
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            coins = await wallet.select_coins(uint64(AMOUNT_TO_SEND), action_scope)
            coin_list = list(coins)
            await wallet.generate_signed_transaction(
                uint64(AMOUNT_TO_SEND),
                bytes32([0] * 32),
                action_scope,
                uint64(0),
                coins=coins,
                origin_id=coin_list[2].name(),
            )
        [tx] = action_scope.side_effects.transactions
        assert tx.spend_bundle is not None
        paid_coin = [coin for coin in tx.spend_bundle.additions() if coin.amount == AMOUNT_TO_SEND][0]
        assert paid_coin.parent_coin_info == coin_list[2].name()
        [tx] = await wallet.wallet_state_manager.add_pending_transactions([tx])

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * AMOUNT_TO_SEND,
                            "spendable_balance": -1 * AMOUNT_TO_SEND,  # used exact amount
                            "max_send_amount": -1 * AMOUNT_TO_SEND,  # used exact amount
                            "pending_change": 0,  # used exact amount
                            "pending_coin_removal_count": len(coins),
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * AMOUNT_TO_SEND,
                            "spendable_balance": 0,  # used exact amount
                            "max_send_amount": 0,  # used exact amount
                            "pending_change": 0,  # used exact amount
                            "unspent_coin_count": -len(coins),
                            "pending_coin_removal_count": -len(coins),
                        }
                    },
                )
            ]
        )


def test_get_wallet_db_path_v2_r1() -> None:
    root_path: Path = Path("/x/y/z/.chia/mainnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v2_r1_CHALLENGE_KEY.sqlite",
        "selected_network": "mainnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_mainnet_1234567890.sqlite")


def test_get_wallet_db_path_v2() -> None:
    root_path: Path = Path("/x/y/z/.chia/mainnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v2_CHALLENGE_KEY.sqlite",
        "selected_network": "mainnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_mainnet_1234567890.sqlite")


def test_get_wallet_db_path_v1() -> None:
    root_path: Path = Path("/x/y/z/.chia/mainnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v1_CHALLENGE_KEY.sqlite",
        "selected_network": "mainnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_mainnet_1234567890.sqlite")


def test_get_wallet_db_path_testnet() -> None:
    root_path: Path = Path("/x/y/z/.chia/testnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v2_CHALLENGE_KEY.sqlite",
        "selected_network": "testnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_testnet_1234567890.sqlite")


@pytest.mark.anyio
async def test_wallet_has_no_server(
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    full_nodes, wallets, bt = simulator_and_wallet
    wallet_node, wallet_server = wallets[0]

    assert wallet_server.webserver is None
