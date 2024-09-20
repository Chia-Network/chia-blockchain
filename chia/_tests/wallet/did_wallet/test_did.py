from __future__ import annotations

import dataclasses
import json
from typing import Optional

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert
from chia.rpc.wallet_request_types import DIDGetCurrentCoinInfo, DIDGetRecoveryInfo
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.peer_info import PeerInfo
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.condition_tools import conditions_dict_for_solution
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.singleton import create_singleton_puzzle
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


async def get_wallet_num(wallet_manager):
    return len(await wallet_manager.get_all_wallet_info_entries())


def get_parent_num(did_wallet: DIDWallet):
    return len(did_wallet.did_info.parent_info)


class TestDIDWallet:
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_creation_from_coin_spend(
        self, self_hostname, two_nodes_two_wallets_with_same_keys: OldSimulatorsAndWallets, trusted
    ):
        """
        Verify that DIDWallet.create_new_did_wallet_from_coin_spend() is called after Singleton creation on
        the blockchain, and that the wallet is created in the second wallet node.
        """
        full_nodes, wallets, _ = two_nodes_two_wallets_with_same_keys
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        ph0 = await wallet_0.get_new_puzzlehash()
        ph1 = await wallet_1.get_new_puzzlehash()

        sk0 = await wallet_node_0.wallet_state_manager.get_private_key(ph0)
        sk1 = await wallet_node_1.wallet_state_manager.get_private_key(ph1)
        assert sk0 == sk1

        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_1.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }

        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
        await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        await full_node_api.farm_blocks_to_wallet(1, wallet_0)
        await full_node_api.farm_blocks_to_wallet(1, wallet_1)

        # Wallet1 sets up DIDWallet1 without any backup set
        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_0.wallet_state_manager, wallet_0, uint64(101), action_scope
            )

        with pytest.raises(RuntimeError):
            assert await did_wallet_0.get_coin() == set()
        assert await did_wallet_0.get_info_for_recovery() is None

        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1])

        await time_out_assert(15, did_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_pending_change_balance, 0)

        await full_node_api.farm_blocks_to_wallet(1, wallet_0)

        #######################
        all_node_0_wallets = await wallet_node_0.wallet_state_manager.user_store.get_all_wallet_info_entries()
        all_node_1_wallets = await wallet_node_1.wallet_state_manager.user_store.get_all_wallet_info_entries()
        assert (
            json.loads(all_node_0_wallets[1].data)["current_inner"]
            == json.loads(all_node_1_wallets[1].data)["current_inner"]
        )

    # TODO: Porting this test to this fixture revealed some balance peculiarities. Fix them.
    @pytest.mark.parametrize(
        "wallet_environments",
        [
            {
                "num_environments": 3,
                "blocks_needed": [1, 1, 1],
            }
        ],
        indirect=True,
    )
    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(reason="irrelevant")
    async def test_creation_from_backup_file(self, wallet_environments: WalletTestFramework) -> None:
        env_0 = wallet_environments.environments[0]
        env_1 = wallet_environments.environments[1]
        env_2 = wallet_environments.environments[2]

        env_0.wallet_aliases = {
            "xch": 1,
            "did": 2,
        }
        env_1.wallet_aliases = {
            "xch": 1,
            "did": 2,
        }
        env_2.wallet_aliases = {
            "xch": 1,
            "did": 2,
        }

        # Wallet1 sets up DIDWallet1 without any backup set
        async with env_0.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
                env_0.wallet_state_manager, env_0.xch_wallet, uint64(101), action_scope
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "unconfirmed_wallet_balance": -101,
                            "<=#spendable_balance": -101,
                            "<=#max_send_amount": -101,
                            ">=#pending_change": 1,
                            "pending_coin_removal_count": 1,
                        },
                        "did": {
                            "init": True,
                            "unconfirmed_wallet_balance": 101,
                            "pending_change": 202,  # TODO: this is not correct, fix this
                            "pending_coin_removal_count": 2,  # TODO: this might not be correct
                        },
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": -101,
                            ">=#spendable_balance": 1,
                            ">=#max_send_amount": 1,
                            "<=#pending_change": -1,
                            "pending_coin_removal_count": -1,
                        },
                        "did": {
                            "confirmed_wallet_balance": 101,
                            "spendable_balance": 101,
                            "max_send_amount": 101,
                            "unspent_coin_count": 1,
                            "pending_change": -202,  # TODO: this is not correct, fix this
                            "pending_coin_removal_count": -2,  # TODO: this might not be correct
                        },
                    },
                ),
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

        # Wallet1 sets up DIDWallet_1 with DIDWallet_0 as backup
        backup_ids = [bytes32.from_hexstr(did_wallet_0.get_my_DID())]

        async with env_1.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                env_1.wallet_state_manager, env_1.xch_wallet, uint64(201), action_scope, backup_ids
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "unconfirmed_wallet_balance": -201,
                            "<=#spendable_balance": -201,
                            "<=#max_send_amount": -201,
                            ">=#pending_change": 1,
                            "pending_coin_removal_count": 1,
                        },
                        "did": {
                            "init": True,
                            "unconfirmed_wallet_balance": 201,
                            "pending_change": 402,  # TODO: this is not correct, fix this
                            "pending_coin_removal_count": 2,  # TODO: this might not be correct
                        },
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": -201,
                            ">=#spendable_balance": 1,
                            ">=#max_send_amount": 1,
                            "<=#pending_change": -1,
                            "pending_coin_removal_count": -1,
                        },
                        "did": {
                            "confirmed_wallet_balance": 201,
                            "spendable_balance": 201,
                            "max_send_amount": 201,
                            "unspent_coin_count": 1,
                            "pending_change": -402,  # TODO: this is not correct, fix this
                            "pending_coin_removal_count": -2,  # TODO: this might not be correct
                        },
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

        backup_data = did_wallet_1.create_backup()

        # Wallet2 recovers DIDWallet2 to a new set of keys
        await env_2.rpc_client.create_new_did_wallet(
            uint64(1),
            DEFAULT_TX_CONFIG,
            type="recovery",
            backup_data=backup_data,
        )
        did_wallet_2 = env_2.wallet_state_manager.get_wallet(id=uint32(2), required_type=DIDWallet)
        recovery_info = await env_2.rpc_client.did_get_recovery_info(
            DIDGetRecoveryInfo(uint32(env_2.wallet_aliases["did"]))
        )
        assert recovery_info.wallet_id == env_2.wallet_aliases["did"]
        assert recovery_info.backup_dids == backup_ids
        current_coin_info_response = await env_0.rpc_client.did_get_current_coin_info(
            DIDGetCurrentCoinInfo(uint32(env_0.wallet_aliases["did"]))
        )
        # TODO: this check is kind of weak, we should research when this endpoint might actually be useful
        assert current_coin_info_response.wallet_id == env_0.wallet_aliases["did"]
        async with env_0.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            message_spend_bundle, attest_data = await did_wallet_0.create_attestment(
                recovery_info.coin_name, recovery_info.newpuzhash, recovery_info.pubkey, action_scope
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "did": {
                            "spendable_balance": -101,
                            "pending_change": 101,
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        "did": {
                            "spendable_balance": 101,
                            "pending_change": -101,
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        "did": {
                            "init": True,
                        }
                    },
                    post_block_balance_updates={},
                ),
            ]
        )

        (
            test_info_list,
            test_message_spend_bundle,
        ) = await did_wallet_2.load_attest_files_for_recovery_spend([attest_data])
        assert message_spend_bundle == test_message_spend_bundle

        async with env_2.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            assert did_wallet_2.did_info.temp_coin is not None
            await did_wallet_2.recovery_spend(
                did_wallet_2.did_info.temp_coin,
                recovery_info.newpuzhash,
                test_info_list,
                recovery_info.pubkey,
                test_message_spend_bundle,
                action_scope,
            )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        "did": {
                            "confirmed_wallet_balance": -201,
                            "unconfirmed_wallet_balance": -201,
                            "spendable_balance": -201,
                            "max_send_amount": -201,
                            "unspent_coin_count": -1,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        "did": {
                            "unconfirmed_wallet_balance": 201,
                            "pending_coin_removal_count": 2,
                        }
                    },
                    post_block_balance_updates={
                        "did": {
                            "confirmed_wallet_balance": 201,
                            "spendable_balance": 201,
                            "max_send_amount": 201,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -2,
                        }
                    },
                ),
            ]
        )

        for wallet in [did_wallet_0, did_wallet_1, did_wallet_2]:
            assert wallet.wallet_state_manager.wallets[wallet.id()] == wallet

        some_ph = bytes32(32 * b"\2")
        async with env_2.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            await did_wallet_2.create_exit_spend(some_ph, action_scope)

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
                WalletStateTransition(
                    pre_block_balance_updates={
                        "did": {
                            "unconfirmed_wallet_balance": -201,
                            "spendable_balance": -201,
                            # "max_send_amount": -201,  # TODO: Uncomment this
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        "did": {
                            "confirmed_wallet_balance": -201,
                            "max_send_amount": -201,  # TODO: Delete this when uncommented above
                            "unspent_coin_count": -1,
                            "pending_coin_removal_count": -1,
                        }
                    },
                ),
            ]
        )

        async def get_coins_with_ph() -> bool:
            coins = await wallet_environments.full_node.full_node.coin_store.get_coin_records_by_puzzle_hash(
                True, some_ph
            )
            return len(coins) == 1

        await time_out_assert(15, get_coins_with_ph, True)

        for wallet in [did_wallet_0, did_wallet_1]:
            assert wallet.wallet_state_manager.wallets[wallet.id()] == wallet

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_did_recovery_with_multiple_backup_dids(self, self_hostname, two_wallet_nodes, trusted):
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

        await full_node_api.farm_blocks_to_wallet(1, wallet)
        await full_node_api.farm_blocks_to_wallet(1, wallet2)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager, wallet, uint64(101), action_scope
            )
        assert did_wallet.get_name() == "Profile 1"
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)

        recovery_list = [bytes.fromhex(did_wallet.get_my_DID())]

        async with wallet2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_2.wallet_state_manager, wallet2, uint64(101), action_scope, recovery_list
            )

        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet_2.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_2.get_unconfirmed_balance, 101)

        assert did_wallet_2.did_info.backup_ids == recovery_list

        recovery_list.append(bytes.fromhex(did_wallet_2.get_my_DID()))

        async with wallet2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_3: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_2.wallet_state_manager, wallet2, uint64(201), action_scope, recovery_list
            )

        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        assert did_wallet_3.did_info.backup_ids == recovery_list
        await time_out_assert(15, did_wallet_3.get_confirmed_balance, 201)
        await time_out_assert(15, did_wallet_3.get_unconfirmed_balance, 201)
        coin = await did_wallet_3.get_coin()

        backup_data = did_wallet_3.create_backup()

        async with wallet_node.wallet_state_manager.lock:
            did_wallet_4 = await DIDWallet.create_new_did_wallet_from_recovery(
                wallet_node.wallet_state_manager,
                wallet,
                backup_data,
            )
        assert did_wallet_4.get_name() == "Profile 2"

        pubkey = (
            await did_wallet_4.wallet_state_manager.get_unused_derivation_record(did_wallet_2.wallet_info.id)
        ).pubkey
        new_ph = did_wallet_4.did_info.temp_puzhash
        async with did_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            message_spend_bundle, attest1 = await did_wallet.create_attestment(
                coin.name(), new_ph, pubkey, action_scope
            )

        async with did_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope_2:
            message_spend_bundle2, attest2 = await did_wallet_2.create_attestment(
                coin.name(), new_ph, pubkey, action_scope_2
            )

        message_spend_bundle = message_spend_bundle.aggregate([message_spend_bundle, message_spend_bundle2])

        (
            test_info_list,
            test_message_spend_bundle,
        ) = await did_wallet_4.load_attest_files_for_recovery_spend([attest1, attest2])
        assert message_spend_bundle == test_message_spend_bundle

        await full_node_api.process_transaction_records(
            records=[*action_scope.side_effects.transactions, *action_scope_2.side_effects.transactions]
        )
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, did_wallet_4.get_confirmed_balance, 0)
        await time_out_assert(15, did_wallet_4.get_unconfirmed_balance, 0)
        async with did_wallet_4.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_4.recovery_spend(coin, new_ph, test_info_list, pubkey, message_spend_bundle, action_scope)
        await full_node_api.process_transaction_records(action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet_4.get_confirmed_balance, 201)
        await time_out_assert(15, did_wallet_4.get_unconfirmed_balance, 201)
        await time_out_assert(15, did_wallet_3.get_confirmed_balance, 0)
        await time_out_assert(15, did_wallet_3.get_unconfirmed_balance, 0)

        for wallet in [did_wallet, did_wallet_2, did_wallet_3, did_wallet_4]:
            assert wallet.wallet_state_manager.wallets[wallet.id()] == wallet

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_did_recovery_with_empty_set(self, self_hostname, two_wallet_nodes, trusted):
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

        await full_node_api.farm_blocks_to_wallet(1, wallet)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager, wallet, uint64(101), action_scope
            )

        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        coin = await did_wallet.get_coin()
        info = Program.to([])
        pubkey = (await did_wallet.wallet_state_manager.get_unused_derivation_record(did_wallet.wallet_info.id)).pubkey
        with pytest.raises(Exception):  # We expect a CLVM 80 error for this test
            async with did_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
                await did_wallet.recovery_spend(
                    coin, ph, info, pubkey, WalletSpendBundle([], AugSchemeMPL.aggregate([])), action_scope
                )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_did_find_lost_did(self, self_hostname, two_wallet_nodes, trusted):
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await full_node_api.farm_blocks_to_wallet(1, wallet)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager, wallet, uint64(101), action_scope
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        # Delete the coin and wallet
        coin = await did_wallet.get_coin()
        await wallet_node.wallet_state_manager.coin_store.delete_coin_record(coin.name())
        await time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        await wallet_node.wallet_state_manager.user_store.delete_wallet(did_wallet.wallet_info.id)
        wallet_node.wallet_state_manager.wallets.pop(did_wallet.wallet_info.id)
        assert len(wallet_node.wallet_state_manager.wallets) == 1
        # Find lost DID
        resp = await api_0.did_find_lost_did({"coin_id": did_wallet.did_info.origin_coin.name().hex()})
        assert resp["success"]
        did_wallets = list(
            filter(
                lambda w: (w.type == WalletType.DECENTRALIZED_ID),
                await wallet_node.wallet_state_manager.get_all_wallet_info_entries(),
            )
        )
        did_wallet: Optional[DIDWallet] = wallet_node.wallet_state_manager.wallets[did_wallets[0].id]
        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        # Spend DID
        recovery_list = [bytes32.fromhex(did_wallet.get_my_DID())]
        await did_wallet.update_recovery_list(recovery_list, uint64(1))
        assert did_wallet.did_info.backup_ids == recovery_list
        async with did_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet.create_update_spend(action_scope)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        # Delete the coin and change inner puzzle
        coin = await did_wallet.get_coin()
        await wallet_node.wallet_state_manager.coin_store.delete_coin_record(coin.name())
        await time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        new_inner_puzzle = await did_wallet.get_new_did_innerpuz()
        did_wallet.did_info = dataclasses.replace(did_wallet.did_info, current_inner=new_inner_puzzle)
        # Recovery the coin
        resp = await api_0.did_find_lost_did({"coin_id": did_wallet.did_info.origin_coin.name().hex()})
        assert resp["success"]
        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        assert did_wallet.did_info.current_inner != new_inner_puzzle

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_did_attest_after_recovery(self, self_hostname, two_wallet_nodes, trusted):
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await full_node_api.farm_blocks_to_wallet(1, wallet)
        await full_node_api.farm_blocks_to_wallet(1, wallet2)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager, wallet, uint64(101), action_scope
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        recovery_list = [bytes.fromhex(did_wallet.get_my_DID())]

        async with wallet2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_2.wallet_state_manager, wallet2, uint64(101), action_scope, recovery_list
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(25, did_wallet_2.get_confirmed_balance, 101)
        await time_out_assert(25, did_wallet_2.get_unconfirmed_balance, 101)
        assert did_wallet_2.did_info.backup_ids == recovery_list

        # Update coin with new ID info
        recovery_list = [bytes.fromhex(did_wallet_2.get_my_DID())]
        await did_wallet.update_recovery_list(recovery_list, uint64(1))
        assert did_wallet.did_info.backup_ids == recovery_list
        async with did_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet.create_update_spend(action_scope)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)

        # DID Wallet 2 recovers into DID Wallet 3 with new innerpuz
        backup_data = did_wallet_2.create_backup()

        async with wallet_node.wallet_state_manager.lock:
            did_wallet_3 = await DIDWallet.create_new_did_wallet_from_recovery(
                wallet_node.wallet_state_manager,
                wallet,
                backup_data,
            )
        new_ph = await did_wallet_3.get_new_did_inner_hash()
        coin = await did_wallet_2.get_coin()
        pubkey = (
            await did_wallet_3.wallet_state_manager.get_unused_derivation_record(did_wallet_3.wallet_info.id)
        ).pubkey
        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        async with did_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            message_spend_bundle, attest_data = await did_wallet.create_attestment(
                coin.name(), new_ph, pubkey, action_scope
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        (
            info,
            message_spend_bundle,
        ) = await did_wallet_3.load_attest_files_for_recovery_spend([attest_data])
        async with did_wallet_3.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_3.recovery_spend(coin, new_ph, info, pubkey, message_spend_bundle, action_scope)
        await full_node_api.process_transaction_records(action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet_3.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_3.get_unconfirmed_balance, 101)

        # DID Wallet 1 recovery spends into DID Wallet 4
        backup_data = did_wallet.create_backup()

        async with wallet_node_2.wallet_state_manager.lock:
            did_wallet_4 = await DIDWallet.create_new_did_wallet_from_recovery(
                wallet_node_2.wallet_state_manager,
                wallet2,
                backup_data,
            )
        coin = await did_wallet.get_coin()
        new_ph = await did_wallet_4.get_new_did_inner_hash()
        pubkey = (
            await did_wallet_4.wallet_state_manager.get_unused_derivation_record(did_wallet_4.wallet_info.id)
        ).pubkey
        async with did_wallet_3.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            message_spend_bundle, attest1 = await did_wallet_3.create_attestment(
                coin.name(), new_ph, pubkey, action_scope
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, wallet.get_pending_change_balance, 0)
        (
            test_info_list,
            test_message_spend_bundle,
        ) = await did_wallet_4.load_attest_files_for_recovery_spend([attest1])
        async with did_wallet_4.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_4.recovery_spend(
                coin, new_ph, test_info_list, pubkey, test_message_spend_bundle, action_scope
            )

        await full_node_api.process_transaction_records(action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        await time_out_assert(15, did_wallet_4.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_4.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 0)

        for wallet in [did_wallet, did_wallet_3, did_wallet_4]:
            assert wallet.wallet_state_manager.wallets[wallet.id()] == wallet

    @pytest.mark.parametrize(
        "with_recovery",
        [True, False],
    )
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_did_transfer(self, self_hostname, two_wallet_nodes, with_recovery, trusted):
        fee = uint64(1000)
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await full_node_api.farm_blocks_to_wallet(1, wallet)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager,
                wallet,
                uint64(101),
                action_scope,
                [bytes(ph)],
                uint64(1),
                {"Twitter": "Test", "GitHub": "测试"},
                fee=fee,
            )
        assert did_wallet_1.get_name() == "Profile 1"
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 101)
        # Transfer DID
        new_puzhash = await wallet2.get_new_puzzlehash()
        async with did_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_1.transfer_did(new_puzhash, fee, with_recovery, action_scope)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        # Check if the DID wallet is created in the wallet2

        await time_out_assert(30, get_wallet_num, 2, wallet_node_2.wallet_state_manager)
        await time_out_assert(30, get_wallet_num, 1, wallet_node.wallet_state_manager)
        # Get the new DID wallet
        did_wallets = list(
            filter(
                lambda w: (w.type == WalletType.DECENTRALIZED_ID),
                await wallet_node_2.wallet_state_manager.get_all_wallet_info_entries(),
            )
        )
        did_wallet_2: Optional[DIDWallet] = wallet_node_2.wallet_state_manager.wallets[did_wallets[0].id]
        assert len(wallet_node.wallet_state_manager.wallets) == 1
        assert did_wallet_1.did_info.origin_coin == did_wallet_2.did_info.origin_coin
        if with_recovery:
            assert did_wallet_1.did_info.backup_ids[0] == did_wallet_2.did_info.backup_ids[0]
            assert did_wallet_1.did_info.num_of_backup_ids_needed == did_wallet_2.did_info.num_of_backup_ids_needed
        metadata = json.loads(did_wallet_2.did_info.metadata)
        assert metadata["Twitter"] == "Test"
        assert metadata["GitHub"] == "测试"

        # Test match_hinted_coin
        assert await did_wallet_2.match_hinted_coin(
            await did_wallet_2.get_coin(),
            new_puzhash,
        )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_update_recovery_list(self, self_hostname, two_wallet_nodes, trusted):
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await full_node_api.farm_blocks_to_wallet(1, wallet)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager, wallet, uint64(101), action_scope, []
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 101)
        await did_wallet_1.update_recovery_list([bytes(ph)], 1)
        async with did_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_1.create_update_spend(action_scope)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 101)
        assert did_wallet_1.did_info.backup_ids[0] == bytes(ph)
        assert did_wallet_1.did_info.num_of_backup_ids_needed == 1

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_get_info(self, self_hostname, two_wallet_nodes, trusted):
        fee = uint64(1000)
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet1 = wallet_node_2.wallet_state_manager.main_wallet
        ph1 = await wallet1.get_new_puzzlehash()
        api_0 = WalletRpcApi(wallet_node)
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await full_node_api.farm_blocks_to_wallet(count=2, wallet=wallet)
        did_amount = uint64(101)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager,
                wallet,
                did_amount,
                action_scope,
                [],
                metadata={"twitter": "twitter"},
                fee=fee,
            )

        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=15)

        assert await did_wallet_1.get_confirmed_balance() == did_amount
        assert await did_wallet_1.get_unconfirmed_balance() == did_amount
        response = await api_0.did_get_info({"coin_id": did_wallet_1.did_info.origin_coin.name().hex()})
        assert response["did_id"] == encode_puzzle_hash(did_wallet_1.did_info.origin_coin.name(), AddressType.DID.value)
        assert response["launcher_id"] == did_wallet_1.did_info.origin_coin.name().hex()
        assert response["full_puzzle"].to_program() == create_singleton_puzzle(
            did_wallet_1.did_info.current_inner, did_wallet_1.did_info.origin_coin.name()
        )
        assert response["metadata"]["twitter"] == "twitter"
        assert response["latest_coin"] == (await did_wallet_1.get_coin()).name().hex()
        assert response["num_verification"] == 0
        assert response["recovery_list_hash"] == Program(Program.to([])).get_tree_hash().hex()
        assert decode_puzzle_hash(response["p2_address"]).hex() == response["hints"][0]

        # Test non-singleton coin
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            coin = (await wallet.select_coins(uint64(1), action_scope)).pop()
        assert coin.amount % 2 == 1
        coin_id = coin.name()
        response = await api_0.did_get_info({"coin_id": coin_id.hex()})
        assert not response["success"]

        # Test multiple odd coins
        odd_amount = uint64(1)
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            async with action_scope.use() as interface:
                interface.side_effects.selected_coins.append(coin)
            coin_1 = (await wallet.select_coins(odd_amount, action_scope)).pop()
        assert coin_1.amount % 2 == 0
        async with wallet.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG.override(excluded_coin_ids=[coin_id]), push=True
        ) as action_scope:
            await wallet.generate_signed_transaction(odd_amount, ph1, action_scope, fee)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_2, timeout=15)

        assert await wallet1.get_confirmed_balance() == odd_amount
        with pytest.raises(ValueError):
            await api_0.did_get_info({"coin_id": coin_1.name().hex()})

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_message_spend(self, self_hostname, two_wallet_nodes, trusted):
        fee = uint64(1000)
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

        await full_node_api.farm_blocks_to_wallet(1, wallet)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager, wallet, uint64(101), action_scope, [], fee=fee
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 101)
        response = await api_0.did_message_spend(
            {"wallet_id": did_wallet_1.wallet_id, "coin_announcements": ["0abc"], "puzzle_announcements": ["0def"]}
        )
        spend = response["spend_bundle"].coin_spends[0]
        conditions = conditions_dict_for_solution(
            spend.puzzle_reveal, spend.solution, wallet.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM
        )

        assert len(conditions[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT]) == 1
        assert conditions[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT][0].vars[0].hex() == "0abc"
        assert len(conditions[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]) == 1
        assert conditions[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT][0].vars[0].hex() == "0def"

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_update_metadata(self, self_hostname, two_wallet_nodes, trusted):
        fee = uint64(1000)
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        expected_confirmed_balance = await full_node_api.farm_blocks_to_wallet(count=2, wallet=wallet)
        did_amount = uint64(101)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager, wallet, did_amount, action_scope, [], fee=fee
            )
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=15)

        expected_confirmed_balance -= did_amount + fee
        assert await did_wallet_1.get_confirmed_balance() == did_amount
        assert await did_wallet_1.get_unconfirmed_balance() == did_amount
        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance
        puzhash = did_wallet_1.did_info.current_inner.get_tree_hash()
        parent_num = get_parent_num(did_wallet_1)

        bad_metadata = {"Twitter": {"url": "http://www.twitter.com"}}
        with pytest.raises(ValueError) as e:
            await did_wallet_1.update_metadata(bad_metadata)
        assert e.match("Metadata key value pairs must be strings.")

        metadata = {}
        metadata["Twitter"] = "http://www.twitter.com"
        await did_wallet_1.update_metadata(metadata)
        async with did_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_1.create_update_spend(action_scope, fee)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])

        expected_confirmed_balance -= fee

        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=15)

        assert await did_wallet_1.get_confirmed_balance() == did_amount
        assert await did_wallet_1.get_unconfirmed_balance() == did_amount

        assert get_parent_num(did_wallet_1) == parent_num + 2
        assert puzhash != did_wallet_1.did_info.current_inner.get_tree_hash()
        assert await wallet.get_confirmed_balance() == expected_confirmed_balance
        assert await wallet.get_unconfirmed_balance() == expected_confirmed_balance

        assert did_wallet_1.did_info.metadata.find("Twitter") > 0

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_did_sign_message(self, self_hostname, two_wallet_nodes, trusted):
        fee = uint64(1000)
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        api_0 = WalletRpcApi(wallet_node)
        ph = await wallet.get_new_puzzlehash()

        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await full_node_api.farm_blocks_to_wallet(1, wallet)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager,
                wallet,
                uint64(101),
                action_scope,
                [bytes(ph)],
                uint64(1),
                {"Twitter": "Test", "GitHub": "测试"},
                fee=fee,
            )
        assert did_wallet_1.get_name() == "Profile 1"
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
        # Test general string
        message = "Hello World"
        response = await api_0.sign_message_by_id(
            {
                "id": encode_puzzle_hash(did_wallet_1.did_info.origin_coin.name(), AddressType.DID.value),
                "message": message,
            }
        )
        puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))
        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            puzzle.get_tree_hash(),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )
        # Test hex string
        message = "0123456789ABCDEF"
        response = await api_0.sign_message_by_id(
            {
                "id": encode_puzzle_hash(did_wallet_1.did_info.origin_coin.name(), AddressType.DID.value),
                "message": message,
                "is_hex": True,
            }
        )
        puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            puzzle.get_tree_hash(),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )

        # Test BLS sign string
        message = "Hello World"
        response = await api_0.sign_message_by_id(
            {
                "id": encode_puzzle_hash(did_wallet_1.did_info.origin_coin.name(), AddressType.DID.value),
                "message": message,
                "is_hex": "False",
                "safe_mode": "False",
            }
        )

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            bytes(message, "utf-8"),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )
        # Test BLS sign hex
        message = "0123456789ABCDEF"
        response = await api_0.sign_message_by_id(
            {
                "id": encode_puzzle_hash(did_wallet_1.did_info.origin_coin.name(), AddressType.DID.value),
                "message": message,
                "is_hex": True,
                "safe_mode": False,
            }
        )

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            bytes.fromhex(message),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_create_did_with_recovery_list(self, self_hostname, two_nodes_two_wallets_with_same_keys, trusted):
        """
        A DID is created on-chain in client0, causing a DID Wallet to be created in client1, which shares the same key.
        This can happen if someone uses the same key on multiple computers, or is syncing a wallet from scratch.

        For this test, we assign a recovery list hash at DID creation time, but the recovery list is not yet available
        to the wallet_node that the DID Wallet is being created in (client1).

        """
        full_nodes, wallets, _ = two_nodes_two_wallets_with_same_keys
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        ph0 = await wallet_0.get_new_puzzlehash()
        ph1 = await wallet_1.get_new_puzzlehash()

        sk0 = await wallet_node_0.wallet_state_manager.get_private_key(ph0)
        sk1 = await wallet_node_1.wallet_state_manager.get_private_key(ph1)
        assert sk0 == sk1

        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_1.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }

        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
        await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        await full_node_api.farm_blocks_to_wallet(1, wallet_0)
        await full_node_api.farm_blocks_to_wallet(1, wallet_1)

        # Node 0 sets up a DID Wallet with a backup set, but num_of_backup_ids_needed=0
        # (a malformed solution, but legal for the clvm puzzle)
        recovery_list = [bytes.fromhex("00" * 32)]
        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_0.wallet_state_manager,
                wallet_0,
                uint64(101),
                action_scope,
                backups_ids=recovery_list,
                num_of_backup_ids_needed=0,
            )

        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0])

        await time_out_assert(15, did_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_pending_change_balance, 0)

        await full_node_api.farm_blocks_to_wallet(1, wallet_0)

        #######################
        all_node_0_wallets = await wallet_node_0.wallet_state_manager.user_store.get_all_wallet_info_entries()
        all_node_1_wallets = await wallet_node_1.wallet_state_manager.user_store.get_all_wallet_info_entries()
        assert len(all_node_0_wallets) == len(all_node_1_wallets)

        # Note that the inner program we expect is different than the on-chain inner.
        # This means that we have more work to do in the checks for the two different spend cases of
        # the DID wallet Singleton
        # assert (
        #    json.loads(all_node_0_wallets[1].data)["current_inner"]
        #    == json.loads(all_node_1_wallets[1].data)["current_inner"]
        # )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_did_resync(self, self_hostname, two_wallet_nodes, trusted) -> None:
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server
        wallet_node_1, wallet_server_1 = wallets[0]
        wallet_node_2, wallet_server_2 = wallets[1]
        wallet = wallet_node_1.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        fee = uint64(0)
        wallet_api_1 = WalletRpcApi(wallet_node_1)
        wallet_api_2 = WalletRpcApi(wallet_node_2)
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_1.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await full_node_api.farm_blocks_to_wallet(1, wallet)

        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_1.wallet_state_manager,
                wallet,
                uint64(101),
                action_scope,
                [bytes32(ph)],
                uint64(1),
                {"Twitter": "Test", "GitHub": "测试"},
                fee=fee,
            )
        assert did_wallet_1.get_name() == "Profile 1"
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_1, wallet_node_2])
        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 101)
        # Transfer DID
        new_puzhash = await wallet2.get_new_puzzlehash()
        async with did_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_1.transfer_did(new_puzhash, fee, True, action_scope=action_scope)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_1, wallet_node_2])
        # Check if the DID wallet is created in the wallet2
        await time_out_assert(30, get_wallet_num, 2, wallet_node_2.wallet_state_manager)
        await time_out_assert(30, get_wallet_num, 1, wallet_node_1.wallet_state_manager)
        did_wallet_2 = wallet_node_2.wallet_state_manager.get_wallet(uint32(2), DIDWallet)
        did_info = did_wallet_2.did_info
        # set flag to reset wallet sync data on start
        await wallet_api_1.set_wallet_resync_on_startup({"enable": True})
        fingerprint_1 = wallet_node_1.logged_in_fingerprint
        await wallet_api_2.set_wallet_resync_on_startup({"enable": True})
        fingerprint_2 = wallet_node_2.logged_in_fingerprint
        # 2 reward coins
        assert len(await wallet_node_1.wallet_state_manager.coin_store.get_all_unspent_coins()) == 2
        # Delete tx records
        await wallet_node_1.wallet_state_manager.tx_store.rollback_to_block(0)
        wallet_node_1._close()
        await wallet_node_1._await_closed()
        wallet_node_2._close()
        await wallet_node_2._await_closed()
        wallet_node_1.config["database_path"] = "wallet/db/blockchain_wallet_v2_test_1_CHALLENGE_KEY.sqlite"
        wallet_node_2.config["database_path"] = "wallet/db/blockchain_wallet_v2_test_2_CHALLENGE_KEY.sqlite"
        # Start resync
        await wallet_node_1._start_with_fingerprint(fingerprint_1)
        await wallet_node_2._start_with_fingerprint(fingerprint_2)
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(b"\00" * 32)))
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_2, timeout=20)
        await time_out_assert(30, get_wallet_num, 1, wallet_node_1.wallet_state_manager)
        await time_out_assert(30, get_wallet_num, 2, wallet_node_2.wallet_state_manager)
        did_wallet_2 = wallet_node_2.wallet_state_manager.get_wallet(uint32(2), DIDWallet)
        assert did_info == did_wallet_2.did_info


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_did_coin_records(wallet_environments: WalletTestFramework, monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup
    wallet_node = wallet_environments.environments[0].node
    wallet = wallet_environments.environments[0].xch_wallet

    # Generate DID wallet
    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {"set_remainder": True},
                    2: {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    1: {"set_remainder": True},
                    2: {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    for _ in range(0, 2):
        async with did_wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            await did_wallet.transfer_did(await wallet.get_puzzle_hash(new=False), uint64(0), True, action_scope)
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {"set_remainder": True},
                        2: {"set_remainder": True},
                    },
                    post_block_balance_updates={
                        1: {"set_remainder": True},
                        2: {"set_remainder": True},
                    },
                ),
                WalletStateTransition(),
            ]
        )

    assert len(await wallet.wallet_state_manager.get_spendable_coins_for_wallet(did_wallet.id())) == 1
