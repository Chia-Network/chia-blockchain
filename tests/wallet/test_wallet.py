from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from blspy import AugSchemeMPL, G1Element, G2Element

from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator, wait_for_coins_in_wallet
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import compute_additions
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.payment import Payment
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import CoinType
from chia.wallet.wallet import CHIP_0002_SIGN_MESSAGE_PREFIX
from chia.wallet.wallet_node import WalletNode, get_wallet_db_path
from chia.wallet.wallet_state_manager import WalletStateManager


class TestWalletSimulator:
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_coinbase(
        self,
        simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 10
        full_nodes, wallets, _ = simulator_and_wallet
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]

        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        wsm: WalletStateManager = wallet_node.wallet_state_manager
        all_txs = await wsm.get_all_transactions(1)

        assert len(all_txs) == num_blocks * 2

        pool_rewards = 0
        farm_rewards = 0

        for tx in all_txs:
            if TransactionType(tx.type) == TransactionType.COINBASE_REWARD:
                pool_rewards += 1
            elif TransactionType(tx.type) == TransactionType.FEE_REWARD:
                farm_rewards += 1

        assert pool_rewards == num_blocks
        assert farm_rewards == num_blocks

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        tx_amount = 10

        tx = await wallet.generate_signed_transaction(
            uint64(tx_amount),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
        )
        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance - tx_amount

        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        expected_confirmed_balance -= tx_amount

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_reuse_address(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        tx_amount = 10

        tx = await wallet.generate_signed_transaction(
            uint64(tx_amount),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
            reuse_puzhash=True,
        )
        assert tx.spend_bundle is not None
        assert len(tx.spend_bundle.coin_spends) == 1
        new_puzhash = [c.puzzle_hash.hex() for c in tx.additions]
        assert tx.spend_bundle.coin_spends[0].coin.puzzle_hash.hex() in new_puzhash
        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance - tx_amount

        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        expected_confirmed_balance -= tx_amount

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_clawback_claim_auto(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 1
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_2.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        wallet_node_2.config["auto_claim"]["tx_fee"] = 100
        wallet_node_2.config["auto_claim"]["batch_size"] = 1
        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance
        await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        tx1 = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 10}],
        )
        await wallet.push_transaction(tx1)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx1])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        tx2 = await wallet.generate_signed_transaction(
            uint64(500),
            await wallet_1.get_new_puzzlehash(),
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 10}],
        )
        await wallet.push_transaction(tx2)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx2])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 2, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 2, 1000, CoinType.CLAWBACK
        )
        tx3 = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 10}],
        )
        await wallet.push_transaction(tx3)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx3])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 3, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 3, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(10, wallet_1.get_confirmed_balance, 4000000000000)
        # Change 3rd coin to test missing metadata case
        clawback_coin_id = tx3.additions[0].name()
        coin_record = await wallet_node_2.wallet_state_manager.coin_store.get_coin_record(clawback_coin_id)
        assert coin_record is not None
        await wallet_node_2.wallet_state_manager.coin_store.add_coin_record(
            dataclasses.replace(coin_record, metadata=None)
        )
        # Claim merkle coin
        wallet_node_2.config["auto_claim"]["enabled"] = True
        await asyncio.sleep(10)
        # Trigger auto claim
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        await asyncio.sleep(5)
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        await asyncio.sleep(5)
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(10, wallet_1.get_confirmed_balance, 4000000000800)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_clawback_clawback(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 1
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_2.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        api_1 = WalletRpcApi(wallet_node_2)
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance

        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        tx = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 500}],
            memos=[b"Test"],
        )

        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        # Check merkle coins
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        txs = await api_0.get_transactions(
            dict(type_filter={"values": [TransactionType.INCOMING_CLAWBACK_SEND], "mode": 1}, wallet_id=1)
        )
        assert await wallet.get_confirmed_balance() == 3999999999500
        # clawback merkle coin
        merkle_coin = tx.additions[0] if tx.additions[0].amount == 500 else tx.additions[1]
        interested_coins = await wallet_node_2.wallet_state_manager.interested_store.get_interested_coin_ids()
        assert merkle_coin.name() in set(interested_coins)
        assert len(txs["transactions"]) == 1
        assert not txs["transactions"][0]["confirmed"]
        assert txs["transactions"][0]["metadata"]["recipient_puzzle_hash"][2:] == normal_puzhash.hex()
        assert txs["transactions"][0]["metadata"]["coin_id"] == merkle_coin.name().hex()
        has_exception = False
        try:
            await api_0.spend_clawback_coins({})
        except ValueError:
            has_exception = True
        assert has_exception
        resp = await api_0.spend_clawback_coins(
            dict({"coin_ids": [normal_puzhash.hex(), merkle_coin.name().hex()], "fee": 1000})
        )
        json.dumps(resp)
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1
        # Wait mempool update
        await time_out_assert_not_none(
            5, full_node_api.full_node.mempool_manager.get_spendbundle, bytes32.from_hexstr(resp["transaction_ids"][0])
        )
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
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
        await time_out_assert(10, wallet.get_confirmed_balance, 3999999999000)
        await time_out_assert(10, wallet_1.get_confirmed_balance, 2000000001000)
        resp = await api_0.get_transactions(dict(wallet_id=1, reverse=True))
        xch_tx = resp["transactions"][0]
        assert list(xch_tx["memos"].values())[0] == b"Test".hex()
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
        interested_coins = await wallet_node_2.wallet_state_manager.interested_store.get_interested_coin_ids()
        assert merkle_coin.name() not in set(interested_coins)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_clawback_sent_self(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 1
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_2.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        wallet_node_2.config["auto_claim"]["enabled"] = False

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        normal_puzhash = await wallet.get_new_puzzlehash()
        # Transfer to normal wallet
        tx = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
            memos=[b"Test"],
        )

        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        # Check merkle coins
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        assert await wallet.get_confirmed_balance() == 3999999999500
        # Claim merkle coin
        await asyncio.sleep(20)
        merkle_coin = tx.additions[0] if tx.additions[0].amount == 500 else tx.additions[1]
        resp = await api_0.spend_clawback_coins(
            dict({"coin_ids": [merkle_coin.name().hex(), normal_puzhash.hex()], "fee": 1000})
        )
        json.dumps(resp)
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1
        # Wait mempool update
        await time_out_assert_not_none(
            5, full_node_api.full_node.mempool_manager.get_spendbundle, bytes32.from_hexstr(resp["transaction_ids"][0])
        )
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(10, wallet.get_confirmed_balance, 6000000000000)

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
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_clawback_claim_manual(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 1
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_2.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        api_1 = WalletRpcApi(wallet_node_2)
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        wallet_node_2.config["auto_claim"]["enabled"] = False

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        tx = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
        )

        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        # Check merkle coins
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        assert await wallet.get_confirmed_balance() == 3999999999500
        # Claim merkle coin
        await asyncio.sleep(20)
        merkle_coin = tx.additions[0] if tx.additions[0].amount == 500 else tx.additions[1]
        resp = await api_1.spend_clawback_coins(
            dict({"coin_ids": [merkle_coin.name().hex(), normal_puzhash.hex()], "fee": 1000})
        )
        json.dumps(resp)
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1
        # Wait mempool update
        await time_out_assert_not_none(
            5, full_node_api.full_node.mempool_manager.get_spendbundle, bytes32.from_hexstr(resp["transaction_ids"][0])
        )
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(10, wallet.get_confirmed_balance, 3999999999500)
        await time_out_assert(10, wallet_1.get_confirmed_balance, 4000000000500)

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
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_clawback_reorg(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 1
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_2.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        wallet_node_2.config["auto_claim"]["enabled"] = False

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        tx = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
        )

        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        # Check merkle coins
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        assert await wallet.get_confirmed_balance() == 3999999999500
        # Reorg before claim
        # Test Reorg mint
        height = full_node_api.full_node.blockchain.get_peak_height()
        assert height is not None
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(height - 2), uint32(height + 1), normal_puzhash, None)
        )
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )

        # Claim merkle coin
        wallet_node_2.config["auto_claim"]["enabled"] = True
        await asyncio.sleep(20)
        # clawback merkle coin
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        # Wait mempool update
        await asyncio.sleep(5)
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(10, wallet.get_confirmed_balance, 1999999999500)
        await time_out_assert(10, wallet_1.get_confirmed_balance, 12000000000500)
        # Reorg after claim
        height = full_node_api.full_node.blockchain.get_peak_height()
        assert height is not None
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(height - 3), uint32(height + 1), normal_puzhash, None)
        )
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_get_clawback_coins(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 1
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_2.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance

        normal_puzhash = await wallet_1.get_new_puzzlehash()
        # Transfer to normal wallet
        tx = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 500}],
        )

        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        # Check merkle coins
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        await time_out_assert(
            20, wallet_node_2.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        assert await wallet.get_confirmed_balance() == 3999999999500
        # clawback merkle coin
        merkle_coin = tx.additions[0] if tx.additions[0].amount == 500 else tx.additions[1]
        resp = await api_0.get_coin_records(dict({"wallet_id": 1, "coin_type": 1}))
        json.dumps(resp)
        assert len(resp["coin_records"]) == 1
        assert resp["coin_records"][0]["id"][2:] == merkle_coin.name().hex()

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_clawback_resync(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 1
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        normal_puzhash = await wallet.get_new_puzzlehash()
        # Transfer to normal wallet
        tx = await wallet.generate_signed_transaction(
            uint64(500),
            normal_puzhash,
            uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
        )
        clawback_coin_id = tx.additions[0].name()
        assert tx.spend_bundle is not None
        await wallet.push_transaction(tx)
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        # Check merkle coins
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 1, 1000, CoinType.CLAWBACK
        )
        assert await wallet.get_confirmed_balance() == 3999999999500
        await asyncio.sleep(10)
        # clawback merkle coin
        resp = await api_0.spend_clawback_coins(
            dict({"coin_ids": [normal_puzhash.hex(), clawback_coin_id.hex()], "fee": 0})
        )
        json.dumps(resp)
        assert resp["success"]
        assert len(resp["transaction_ids"]) == 1
        expected_confirmed_balance += await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)
        await time_out_assert(
            20, wallet_node.wallet_state_manager.coin_store.count_small_unspent, 0, 1000, CoinType.CLAWBACK
        )
        wallet_node_2._close()
        await wallet_node_2._await_closed()
        # set flag to reset wallet sync data on start
        await api_0.set_wallet_resync_on_startup({"enable": True})
        fingerprint = wallet_node.logged_in_fingerprint
        assert wallet_node._wallet_state_manager
        # 2 reward coins, 1 clawbacked coin
        assert len(await wallet_node._wallet_state_manager.coin_store.get_all_unspent_coins()) == 7
        # standard wallet
        assert len(await wallet_node.wallet_state_manager.user_store.get_all_wallet_info_entries()) == 1
        before_txs = await wallet_node.wallet_state_manager.tx_store.get_all_transactions()
        # Delete tx records
        await wallet_node.wallet_state_manager.tx_store.rollback_to_block(0)
        wallet_node._close()
        await wallet_node._await_closed()
        config = load_config(wallet_node.root_path, "config.yaml")
        # check that flag was set in config file
        assert config["wallet"]["reset_sync_for_fingerprint"] == fingerprint
        new_config = wallet_node.config.copy()
        new_config["reset_sync_for_fingerprint"] = config["wallet"]["reset_sync_for_fingerprint"]
        new_config["database_path"] = "wallet/db/blockchain_wallet_v2_test_CHALLENGE_KEY.sqlite"
        wallet_node_2.config = new_config
        wallet_node_2.root_path = wallet_node.root_path
        wallet_node_2.local_keychain = wallet_node.local_keychain
        # use second node to start the same wallet, reusing config and db
        await wallet_node_2._start_with_fingerprint(fingerprint)
        assert wallet_node_2._wallet_state_manager
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(b"\00" * 32)))
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_2, timeout=20)
        after_txs = await wallet_node_2.wallet_state_manager.tx_store.get_all_transactions()
        # transactions should be the same
        assert len(after_txs) == len(before_txs)
        # Check clawback
        clawback_tx = await wallet_node_2.wallet_state_manager.tx_store.get_transaction_record(clawback_coin_id)
        assert clawback_tx is not None
        assert clawback_tx.confirmed
        outgoing_clawback_txs = await wallet_node_2.wallet_state_manager.tx_store.get_transactions_between(
            1, 0, 100, type_filter=TransactionTypeFilter.include([TransactionType.OUTGOING_CLAWBACK])
        )
        assert len(outgoing_clawback_txs) == 1
        assert outgoing_clawback_txs[0].confirmed
        # Check unspent coins
        assert len(await wallet_node_2._wallet_state_manager.coin_store.get_all_unspent_coins()) == 7

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_coinbase_reorg(
        self,
        simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        full_nodes, wallets, _ = simulator_and_wallet
        full_node_api = full_nodes[0]
        fn_server = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        await asyncio.sleep(5)

        permanent_blocks = 3
        extra_blocks = 2

        permanent_funds = await full_node_api.farm_blocks_to_wallet(count=permanent_blocks, wallet=wallet)
        peak = full_node_api.full_node.blockchain.get_peak()
        assert peak is not None
        permanent_height = peak.height
        await full_node_api.farm_blocks_to_wallet(count=extra_blocks, wallet=wallet)

        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(
                uint32(permanent_height), uint32(permanent_height + extra_blocks + 6), bytes32(32 * b"0"), None
            )
        )

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)
        assert await wallet.get_confirmed_balance() == permanent_funds

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
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
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        await full_node_api_0.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0.wallet_state_manager.main_wallet)

        all_blocks = await full_node_api_0.get_all_full_blocks()

        for block in all_blocks:
            await full_node_1.add_block(block)
            await full_node_2.add_block(block)

        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(
            uint64(10),
            bytes32(32 * b"0"),
            uint64(0),
        )
        assert tx.spend_bundle is not None
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)
        await full_node_api_0.wait_transaction_records_entered_mempool(records=[tx])

        # wallet0 <-> sever1
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_1._port)), wallet_0.on_connect)
        await full_node_api_1.wait_transaction_records_entered_mempool(records=[tx])

        # wallet0 <-> sever2
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_2._port)), wallet_0.on_connect)
        await full_node_api_2.wait_transaction_records_entered_mempool(records=[tx])

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction_hop(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 10
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api_0 = full_nodes[0]
        full_node_0 = full_node_api_0.full_node
        server_0 = full_node_0.server

        wallet_node_0, wallet_0_server = wallets[0]
        wallet_node_1, wallet_1_server = wallets[1]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {server_0.node_id.hex(): server_0.node_id.hex()}
            wallet_node_1.config["trusted_peers"] = {server_0.node_id.hex(): server_0.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
        await wallet_0_server.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        await wallet_1_server.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        expected_confirmed_balance = await full_node_api_0.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)

        assert await wallet_0.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet_0.get_unconfirmed_balance() == expected_confirmed_balance

        tx_amount = 10
        tx = await wallet_0.generate_signed_transaction(
            uint64(tx_amount),
            await wallet_node_1.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
        )

        await wallet_0.push_transaction(tx)
        await full_node_api_0.wait_transaction_records_entered_mempool(records=[tx])

        assert await wallet_0.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet_0.get_unconfirmed_balance() == expected_confirmed_balance - tx_amount

        await full_node_api_0.farm_blocks_to_puzzlehash(count=4, guarantee_transaction_blocks=True)
        expected_confirmed_balance -= tx_amount

        # Full node height 17, wallet height 15
        await time_out_assert(20, wallet_0.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet_0.get_unconfirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet_1.get_confirmed_balance, 10)

        tx_amount = 5
        tx = await wallet_1.generate_signed_transaction(
            uint64(tx_amount), await wallet_0.get_new_puzzlehash(), uint64(0)
        )
        await wallet_1.push_transaction(tx)
        await full_node_api_0.wait_transaction_records_entered_mempool(records=[tx])

        await full_node_api_0.farm_blocks_to_puzzlehash(count=4, guarantee_transaction_blocks=True)
        expected_confirmed_balance += tx_amount

        await wallet_0.get_confirmed_balance()
        await wallet_0.get_unconfirmed_balance()
        await wallet_1.get_confirmed_balance()

        await time_out_assert(20, wallet_0.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet_0.get_unconfirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet_1.get_confirmed_balance, 5)

    # @pytest.mark.asyncio
    # async def test_wallet_finds_full_node(self):
    #     node_iters = [
    #         setup_full_node(
    #             test_constants,
    #             "blockchain_test.db",
    #             11234,
    #             introducer_port=11236,
    #             simulator=False,
    #         ),
    #         setup_wallet_node(
    #             11235,
    #             test_constants,
    #             None,
    #             introducer_port=11236,
    #         ),
    #         setup_introducer(11236),
    #     ]
    #
    #     full_node_api = await node_iters[0].__anext__()
    #     wallet, wallet_server = await node_iters[1].__anext__()
    #     introducer, introducer_server = await node_iters[2].__anext__()
    #
    #     async def has_full_node():
    #         outbound: List[WSChiaConnection] = wallet.server.get_outgoing_connections()
    #         for connection in outbound:
    #             if connection.connection_type is NodeType.FULL_NODE:
    #                 return True
    #         return False
    #
    #     await time_out_assert(
    #         2 * 60,
    #         has_full_node,
    #         True,
    #     )
    #     await _teardown_nodes(node_iters)
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction_with_fee(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_1 = full_nodes[0]

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        expected_confirmed_balance = await full_node_1.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance

        tx_amount = 3200000000000
        tx_fee = 10
        tx = await wallet.generate_signed_transaction(
            uint64(tx_amount),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(tx_fee),
        )
        assert tx.spend_bundle is not None

        fees = tx.spend_bundle.fees()
        assert fees == tx_fee

        await wallet.push_transaction(tx)
        await full_node_1.wait_transaction_records_entered_mempool(records=[tx])

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance - tx_amount - tx_fee

        expected_confirmed_balance = await full_node_1.farm_blocks_to_puzzlehash(
            count=num_blocks,
            guarantee_transaction_blocks=True,
        )
        expected_confirmed_balance -= tx_amount + tx_fee

        await time_out_assert(5, wallet.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(5, wallet.get_unconfirmed_balance, expected_confirmed_balance)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction_with_memo(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 2
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_1 = full_nodes[0]

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_2.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        api_1 = WalletRpcApi(wallet_node_2)
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        expected_confirmed_balance = await full_node_1.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance

        tx_amount = 3200000000000
        tx_fee = 10
        ph_2 = await wallet_1.get_new_puzzlehash()
        tx = await wallet.generate_signed_transaction(uint64(tx_amount), ph_2, uint64(tx_fee), memos=[ph_2])
        tx_id = tx.name.hex()
        assert tx.spend_bundle is not None

        fees = tx.spend_bundle.fees()
        assert fees == tx_fee

        await wallet.push_transaction(tx)
        await full_node_1.wait_transaction_records_entered_mempool(records=[tx])
        memos = await api_0.get_transaction_memo(dict(transaction_id=tx_id))
        # test json serialization
        json.dumps(memos)
        assert len(memos[tx_id]) == 1
        assert list(memos[tx_id].values())[0][0] == ph_2.hex()
        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance - tx_amount - tx_fee

        await full_node_1.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        await time_out_assert(15, wallet_1.get_confirmed_balance, tx_amount)
        for coin in tx.additions:
            if coin.amount == tx_amount:
                tx_id = coin.name().hex()
        memos = await api_1.get_transaction_memo(dict(transaction_id=tx_id))
        assert len(memos[tx_id]) == 1
        assert list(memos[tx_id].values())[0][0] == ph_2.hex()

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_create_hit_max_send_amount(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_1 = full_nodes[0]

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        expected_confirmed_balance = await full_node_1.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        await time_out_assert(20, wallet.get_confirmed_balance, expected_confirmed_balance)

        primaries = [Payment(ph, uint64(1000000000 + i)) for i in range(60)]
        tx_split_coins = await wallet.generate_signed_transaction(uint64(1), ph, uint64(0), primaries=primaries)
        assert tx_split_coins.spend_bundle is not None

        await wallet.push_transaction(tx_split_coins)
        await full_node_1.process_transaction_records(records=[tx_split_coins])
        await wait_for_coins_in_wallet(coins=set(tx_split_coins.additions), wallet=wallet)

        max_sent_amount = await wallet.get_max_send_amount()

        # 1) Generate transaction that is under the limit
        transaction_record = await wallet.generate_signed_transaction(
            uint64(max_sent_amount - 1),
            ph,
            uint64(0),
        )

        assert transaction_record.amount == uint64(max_sent_amount - 1)

        # 2) Generate transaction that is equal to limit
        transaction_record = await wallet.generate_signed_transaction(
            uint64(max_sent_amount),
            ph,
            uint64(0),
        )

        assert transaction_record.amount == uint64(max_sent_amount)

        # 3) Generate transaction that is greater than limit
        with pytest.raises(ValueError):
            await wallet.generate_signed_transaction(
                uint64(max_sent_amount + 1),
                ph,
                uint64(0),
            )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_prevent_fee_theft(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_1 = full_nodes[0]

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        expected_confirmed_balance = await full_node_1.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        await time_out_assert(20, wallet.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet.get_unconfirmed_balance, expected_confirmed_balance)

        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance
        tx_amount = 3200000000000
        tx_fee = 300000000000
        tx = await wallet.generate_signed_transaction(
            uint64(tx_amount),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(tx_fee),
        )
        assert tx.spend_bundle is not None

        # extract coin_spend from generated spend_bundle
        for cs in tx.spend_bundle.coin_spends:
            if compute_additions(cs) == []:
                stolen_cs = cs
        # get a legit signature
        stolen_sb = await wallet.sign_transaction([stolen_cs])
        now = uint64(int(time.time()))
        add_list = list(stolen_sb.additions())
        rem_list = list(stolen_sb.removals())
        name = stolen_sb.name()
        stolen_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=bytes32(32 * b"0"),
            amount=uint64(0),
            fee_amount=uint64(stolen_cs.coin.amount),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=stolen_sb,
            additions=add_list,
            removals=rem_list,
            wallet_id=wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=name,
            memos=list(compute_memos(stolen_sb).items()),
        )
        await wallet.push_transaction(stolen_tx)

        await time_out_assert(20, wallet.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet.get_unconfirmed_balance, expected_confirmed_balance - stolen_cs.coin.amount)

        await full_node_1.farm_blocks_to_puzzlehash(count=num_blocks, guarantee_transaction_blocks=True)

        # Funds have not decreased because stolen_tx was rejected
        await time_out_assert(20, wallet.get_confirmed_balance, expected_confirmed_balance)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_tx_reorg(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        permanent_block_count = 4
        reorg_block_count = 3
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        fn_server = full_node_api.full_node.server

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph2 = await wallet_2.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        permanent_funds = await full_node_api.farm_blocks_to_wallet(count=permanent_block_count, wallet=wallet)

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

        # Ensure that we use a coin that we will not reorg out
        tx_amount = 1000
        coins = await wallet.select_coins(amount=uint64(tx_amount))
        coin = next(iter(coins))

        reorg_height = full_node_api.full_node.blockchain.get_peak_height()
        assert reorg_height is not None
        reorg_funds = await full_node_api.farm_blocks_to_wallet(count=reorg_block_count, wallet=wallet)

        tx = await wallet.generate_signed_transaction(uint64(tx_amount), ph2, coins={coin})
        assert tx.spend_bundle is not None
        await wallet.push_transaction(tx)
        await full_node_api.process_transaction_records(records=[tx])
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2], timeout=20)

        assert await wallet.get_confirmed_balance() == permanent_funds + reorg_funds - tx_amount
        assert await wallet_2.get_confirmed_balance() == tx_amount
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

        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2], timeout=20)
        assert await wallet.get_confirmed_balance() == permanent_funds
        assert await wallet_2.get_confirmed_balance() == 0

        # process the resubmitted tx
        for _ in range(10):
            await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
            await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2], timeout=20)

            if (await wallet.get_confirmed_balance() == permanent_funds - tx_amount) and (
                await wallet_2.get_confirmed_balance() == tx_amount
            ):
                break
        else:
            raise Exception("failed to reprocess reorged resubmitted tx")

        unconfirmed = await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(int(wallet.id()))
        assert len(unconfirmed) == 0
        tx_record = await wallet_node.wallet_state_manager.tx_store.get_transaction_record(tx.name)
        assert tx_record is not None
        removed = tx_record.removals[0]
        added = tx_record.additions[0]
        added_1 = tx_record.additions[1]
        wallet_coin_record_rem = await wallet_node.wallet_state_manager.coin_store.get_coin_record(removed.name())
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
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_address_sliding_window(
        self,
        wallet_node_100_pk: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        full_nodes, wallets, _ = wallet_node_100_pk
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
        wallet = wallet_node.wallet_state_manager.main_wallet

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        puzzle_hashes = []
        for i in range(211):
            pubkey = master_sk_to_wallet_sk(wallet_node.wallet_state_manager.private_key, uint32(i)).get_g1()
            puzzle: Program = wallet.puzzle_for_pk(pubkey)
            puzzle_hash: bytes32 = puzzle.get_tree_hash()
            puzzle_hashes.append(puzzle_hash)

        expected_confirmed_balance = 0
        gapped_funds = 0

        expected_confirmed_balance += await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=puzzle_hashes[0])
        gapped_funds += await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=puzzle_hashes[210])
        gapped_funds += await full_node_api.farm_blocks_to_puzzlehash(
            count=1,
            farm_to=puzzle_hashes[114],
            guarantee_transaction_blocks=True,
        )
        await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)

        await time_out_assert(60, wallet.get_confirmed_balance, expected_confirmed_balance)

        expected_confirmed_balance += await full_node_api.farm_blocks_to_puzzlehash(
            count=1,
            farm_to=puzzle_hashes[50],
            guarantee_transaction_blocks=True,
        )
        await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
        expected_confirmed_balance += gapped_funds

        await time_out_assert(60, wallet.get_confirmed_balance, expected_confirmed_balance)

        expected_confirmed_balance += await full_node_api.farm_blocks_to_puzzlehash(count=1, farm_to=puzzle_hashes[113])
        expected_confirmed_balance += await full_node_api.farm_blocks_to_puzzlehash(
            count=1,
            farm_to=puzzle_hashes[209],
            guarantee_transaction_blocks=True,
        )
        await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
        await time_out_assert(60, wallet.get_confirmed_balance, expected_confirmed_balance)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_sign_message(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        api_0 = WalletRpcApi(wallet_node)
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        # Test general string
        message = "Hello World"
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
            {"address": encode_puzzle_hash(ph, "xch"), "message": message, "is_hex": "true"}
        )
        puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            puzzle.get_tree_hash(),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_transaction_options(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet)

        await time_out_assert(20, wallet.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet.get_unconfirmed_balance, expected_confirmed_balance)

        AMOUNT_TO_SEND = 4000000000000
        coins = await wallet.select_coins(uint64(AMOUNT_TO_SEND))
        coin_list = list(coins)

        tx = await wallet.generate_signed_transaction(
            uint64(AMOUNT_TO_SEND),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
            coins=coins,
            origin_id=coin_list[2].name(),
        )
        assert tx.spend_bundle is not None
        paid_coin = [coin for coin in tx.spend_bundle.additions() if coin.amount == AMOUNT_TO_SEND][0]
        assert paid_coin.parent_coin_info == coin_list[2].name()
        await wallet.push_transaction(tx)

        await time_out_assert(20, wallet.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(20, wallet.get_unconfirmed_balance, expected_confirmed_balance - AMOUNT_TO_SEND)
        await time_out_assert(20, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        await full_node_api.farm_blocks_to_puzzlehash(count=num_blocks, guarantee_transaction_blocks=True)
        expected_confirmed_balance -= AMOUNT_TO_SEND

        await time_out_assert(10, wallet.get_confirmed_balance, expected_confirmed_balance)
        await time_out_assert(10, wallet.get_unconfirmed_balance, expected_confirmed_balance)


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
