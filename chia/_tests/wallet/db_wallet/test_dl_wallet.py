from __future__ import annotations

import dataclasses

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.data_layer.data_layer_errors import LauncherCoinNotFoundError
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import ReorgProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.wallet.db_wallet.db_wallet_puzzles import create_mirror_puzzle
from chia.wallet.util.merkle_tree import MerkleTree
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG

pytestmark = pytest.mark.data_layer


async def is_singleton_confirmed(dl_wallet: DataLayerWallet, lid: bytes32) -> bool:
    rec = await dl_wallet.get_latest_singleton(lid)
    if rec is None:
        return False
    if rec.confirmed is True:
        assert rec.confirmed_at_height > 0
        assert rec.timestamp > 0
    return rec.confirmed


class TestDLWallet:
    @pytest.mark.parametrize(
        "wallet_environments",
        [
            {
                "num_environments": 1,
                "blocks_needed": [2],
            }
        ],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes
    @pytest.mark.anyio
    async def test_initial_creation(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        env.wallet_aliases = {
            "xch": 1,
            "dl": 2,
        }

        dl_wallet = await DataLayerWallet.create_new_dl_wallet(env.wallet_state_manager)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        fee = uint64(1_999_999_999_999)

        for i in range(2):
            async with dl_wallet.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=True
            ) as action_scope:
                launcher_id = await dl_wallet.generate_new_reporter(
                    current_root,
                    action_scope,
                    fee=fee,
                )

            assert await dl_wallet.get_latest_singleton(launcher_id) is not None

            await wallet_environments.process_pending_states(
                [
                    WalletStateTransition(
                        pre_block_balance_updates={
                            "xch": {
                                "unconfirmed_wallet_balance": -fee - 1,
                                "spendable_balance": -fee - 1,
                                "max_send_amount": -fee - 1,
                                "pending_coin_removal_count": 2,  # creation + launcher
                            },
                            "dl": {"init": True} if i == 0 else {},
                        },
                        post_block_balance_updates={
                            "xch": {
                                "confirmed_wallet_balance": -fee - 1,
                                "spendable_balance": 0,
                                "max_send_amount": 0,
                                "pending_coin_removal_count": -2,
                                "unspent_coin_count": -2,
                            },
                            "dl": {
                                "unspent_coin_count": 1,
                            },
                        },
                    ),
                ]
            )

            await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)

        new_puz = await dl_wallet.get_new_puzzle()
        assert new_puz

    @pytest.mark.parametrize(
        "wallet_environments",
        [
            {
                "num_environments": 1,
                "blocks_needed": [2],
            }
        ],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes
    @pytest.mark.anyio
    async def test_get_owned_singletons(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        env.wallet_aliases = {
            "xch": 1,
            "dl": 2,
        }

        dl_wallet = await DataLayerWallet.create_new_dl_wallet(env.wallet_state_manager)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        expected_launcher_ids = set()

        fee = uint64(1_999_999_999_999)

        for i in range(2):
            async with dl_wallet.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=True
            ) as action_scope:
                launcher_id = await dl_wallet.generate_new_reporter(current_root, action_scope, fee=fee)
            expected_launcher_ids.add(launcher_id)

            assert await dl_wallet.get_latest_singleton(launcher_id) is not None

            await wallet_environments.process_pending_states(
                [
                    WalletStateTransition(
                        pre_block_balance_updates={
                            "xch": {
                                "unconfirmed_wallet_balance": -fee - 1,
                                "spendable_balance": -fee - 1,
                                "max_send_amount": -fee - 1,
                                "pending_coin_removal_count": 2,  # creation + launcher
                            },
                            "dl": {"init": True} if i == 0 else {},
                        },
                        post_block_balance_updates={
                            "xch": {
                                "confirmed_wallet_balance": -fee - 1,
                                "spendable_balance": 0,
                                "max_send_amount": 0,
                                "pending_coin_removal_count": -2,
                                "unspent_coin_count": -2,
                            },
                            "dl": {
                                "unspent_coin_count": 1,
                            },
                        },
                    ),
                ]
            )

            await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)

        owned_singletons = await dl_wallet.get_owned_singletons()
        owned_launcher_ids = sorted(singleton.launcher_id for singleton in owned_singletons)
        assert owned_launcher_ids == sorted(expected_launcher_ids)

    @pytest.mark.parametrize(
        "wallet_environments",
        [
            {
                "num_environments": 2,
                "blocks_needed": [1, 1],
            }
        ],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes
    @pytest.mark.anyio
    async def test_tracking_non_owned(self, wallet_environments: WalletTestFramework) -> None:
        env_0 = wallet_environments.environments[0]
        env_1 = wallet_environments.environments[1]
        env_0.wallet_aliases = {
            "xch": 1,
            "dl": 2,
        }
        env_1.wallet_aliases = {
            "xch": 1,
            "dl": 2,
        }

        dl_wallet_0 = await DataLayerWallet.create_new_dl_wallet(env_0.wallet_state_manager)
        dl_wallet_1 = await DataLayerWallet.create_new_dl_wallet(env_1.wallet_state_manager)

        peer = env_1.node.get_full_node_peer()

        # Test tracking a launcher id that does not exist
        with pytest.raises(LauncherCoinNotFoundError):
            await dl_wallet_0.track_new_launcher_id(bytes32([1] * 32), peer)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async with dl_wallet_0.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            launcher_id = await dl_wallet_0.generate_new_reporter(current_root, action_scope)

        assert await dl_wallet_0.get_latest_singleton(launcher_id) is not None

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "unconfirmed_wallet_balance": -1,
                            "<=#spendable_balance": -1,
                            "<=#max_send_amount": -1,
                            ">=#pending_change": 1,
                            "pending_coin_removal_count": 1,  # creation + launcher
                        },
                        "dl": {
                            "init": True,
                        },
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": -1,
                            ">=#spendable_balance": 0,
                            ">=#max_send_amount": 0,
                            "<=#pending_change": -1,
                            "pending_coin_removal_count": -1,
                        },
                        "dl": {
                            "unspent_coin_count": 1,
                        },
                    },
                ),
            ]
        )

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)

        await dl_wallet_1.track_new_launcher_id(launcher_id, peer)
        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_1, launcher_id)

        for _ in range(5):
            new_root = MerkleTree([Program.to("root").get_tree_hash()]).calculate_root()
            async with dl_wallet_0.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=True
            ) as action_scope:
                await dl_wallet_0.create_update_state_spend(launcher_id, new_root, action_scope)

            await wallet_environments.process_pending_states(
                [
                    WalletStateTransition(
                        pre_block_balance_updates={
                            "dl": {
                                "pending_coin_removal_count": 1,
                            },
                        },
                        post_block_balance_updates={
                            "dl": {
                                "pending_coin_removal_count": -1,
                            },
                        },
                    ),
                ]
            )

            await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)

        async def do_tips_match() -> bool:
            latest_singleton_0 = await dl_wallet_0.get_latest_singleton(launcher_id)
            latest_singleton_1 = await dl_wallet_1.get_latest_singleton(launcher_id)
            return latest_singleton_0 == latest_singleton_1

        await time_out_assert(15, do_tips_match, True)

        await dl_wallet_1.stop_tracking_singleton(launcher_id)
        assert await dl_wallet_1.get_latest_singleton(launcher_id) is None

        await dl_wallet_1.track_new_launcher_id(launcher_id, peer)
        await time_out_assert(15, do_tips_match, True)

    @pytest.mark.parametrize(
        "wallet_environments",
        [
            {
                "num_environments": 2,
                "blocks_needed": [1, 1],
            }
        ],
        indirect=True,
    )
    @pytest.mark.limit_consensus_modes
    @pytest.mark.anyio
    async def test_lifecycle(self, wallet_environments: WalletTestFramework) -> None:
        env = wallet_environments.environments[0]
        env.wallet_aliases = {
            "xch": 1,
            "dl": 2,
        }

        dl_wallet = await DataLayerWallet.create_new_dl_wallet(env.wallet_state_manager)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async with dl_wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            launcher_id = await dl_wallet.generate_new_reporter(current_root, action_scope)

        assert await dl_wallet.get_latest_singleton(launcher_id) is not None

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "unconfirmed_wallet_balance": -1,
                            "<=#spendable_balance": -1,
                            "<=#max_send_amount": -1,
                            ">=#pending_change": 1,
                            "pending_coin_removal_count": 1,  # creation + launcher
                        },
                        "dl": {
                            "init": True,
                        },
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": -1,
                            ">=#spendable_balance": 0,
                            ">=#max_send_amount": 0,
                            "<=#pending_change": -1,
                            "pending_coin_removal_count": -1,
                        },
                        "dl": {
                            "unspent_coin_count": 1,
                        },
                    },
                ),
            ]
        )

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)

        previous_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert previous_record is not None
        assert previous_record.lineage_proof.amount is not None

        new_root = MerkleTree([Program.to("root").get_tree_hash()]).calculate_root()

        fee = uint64(1_999_999_999_999)

        async with dl_wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            await dl_wallet.generate_signed_transaction(
                [previous_record.lineage_proof.amount],
                [previous_record.inner_puzzle_hash],
                action_scope,
                launcher_id=previous_record.launcher_id,
                new_root_hash=new_root,
                fee=fee,
            )
        assert action_scope.side_effects.transactions[0].spend_bundle is not None
        with pytest.raises(ValueError, match="is currently pending"):
            async with dl_wallet.wallet_state_manager.new_action_scope(
                wallet_environments.tx_config, push=False
            ) as failed_action_scope:
                await dl_wallet.generate_signed_transaction(
                    [previous_record.lineage_proof.amount],
                    [previous_record.inner_puzzle_hash],
                    failed_action_scope,
                    coins={
                        next(
                            rem
                            for rem in action_scope.side_effects.transactions[0].spend_bundle.removals()
                            if rem.amount == 1
                        )
                    },
                    fee=fee,
                )

        new_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert new_record is not None
        assert new_record != previous_record
        assert not new_record.confirmed

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "unconfirmed_wallet_balance": -fee,
                            # these match exactly because of our change from the creation
                            "spendable_balance": -fee,
                            "max_send_amount": -fee,
                            "pending_coin_removal_count": 2,
                        },
                        "dl": {
                            "pending_coin_removal_count": 1,
                        },
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": -fee,
                            "spendable_balance": 0,
                            "max_send_amount": 0,
                            "pending_coin_removal_count": -2,
                            "unspent_coin_count": -2,
                        },
                        "dl": {
                            "pending_coin_removal_count": -1,
                        },
                    },
                ),
            ]
        )

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)

        dl_coin_record = await dl_wallet.wallet_state_manager.coin_store.get_coin_record(new_record.coin_id)
        assert dl_coin_record is not None
        assert await dl_wallet.match_hinted_coin(dl_coin_record.coin, new_record.launcher_id)

        previous_record = await dl_wallet.get_latest_singleton(launcher_id)

        new_root = MerkleTree([Program.to("new root").get_tree_hash()]).calculate_root()
        async with dl_wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            await dl_wallet.create_update_state_spend(launcher_id, new_root, action_scope)
        new_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert new_record is not None
        assert new_record != previous_record
        assert not new_record.confirmed

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "dl": {
                            "pending_coin_removal_count": 1,
                        },
                    },
                    post_block_balance_updates={
                        "dl": {
                            "pending_coin_removal_count": -1,
                        },
                    },
                ),
            ]
        )

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)


async def is_singleton_confirmed_and_root(dl_wallet: DataLayerWallet, lid: bytes32, root: bytes32) -> bool:
    rec = await dl_wallet.get_latest_singleton(lid)
    if rec is None:
        return False
    if rec.confirmed is True:
        assert rec.confirmed_at_height > 0
        assert rec.timestamp > 0
    return rec.confirmed and rec.root == root


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "blocks_needed": [3, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes
@pytest.mark.anyio
async def test_mirrors(wallet_environments: WalletTestFramework) -> None:
    env_1 = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]
    env_1.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }

    dl_wallet_1 = await DataLayerWallet.create_new_dl_wallet(env_1.wallet_state_manager)
    dl_wallet_2 = await DataLayerWallet.create_new_dl_wallet(env_2.wallet_state_manager)

    async with dl_wallet_1.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_1 = await dl_wallet_1.generate_new_reporter(bytes32.zeros, action_scope)

    async with dl_wallet_2.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        launcher_id_2 = await dl_wallet_2.generate_new_reporter(bytes32.zeros, action_scope)

    assert await dl_wallet_1.get_latest_singleton(launcher_id_1) is not None
    assert await dl_wallet_2.get_latest_singleton(launcher_id_2) is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,  # creation + launcher
                    },
                    "dl": {
                        "init": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
        * 2
    )

    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_1, launcher_id_1, bytes32.zeros)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_2, launcher_id_2, bytes32.zeros)

    peer_1 = env_1.node.get_full_node_peer()
    await dl_wallet_1.track_new_launcher_id(launcher_id_2, peer_1)
    await env_1.change_balances({"dl": {"unspent_coin_count": 1}})
    peer_2 = env_2.node.get_full_node_peer()
    await dl_wallet_2.track_new_launcher_id(launcher_id_1, peer_2)
    await env_2.change_balances({"dl": {"unspent_coin_count": 1}})
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_1, launcher_id_2, bytes32.zeros)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_2, launcher_id_1, bytes32.zeros)

    fee = uint64(1_999_999_999_999)
    mirror_amount = uint64(3)

    async with dl_wallet_1.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await dl_wallet_1.create_new_mirror(launcher_id_2, mirror_amount, [b"foo", b"bar"], action_scope, fee=fee)

    additions: list[Coin] = []
    for tx in action_scope.side_effects.transactions:
        if tx.spend_bundle is not None:
            additions.extend(tx.spend_bundle.additions())

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee - mirror_amount,
                        # these match exactly because of our change from the creation
                        "<=#spendable_balance": -fee - mirror_amount,
                        "<=#max_send_amount": -fee - mirror_amount,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 3,
                    },
                    "dl": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee - mirror_amount,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -3,
                        "unspent_coin_count": -2,
                    },
                    "dl": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )

    mirror_coin: Coin = next(c for c in additions if c.puzzle_hash == create_mirror_puzzle().get_tree_hash())
    mirror = Mirror(
        bytes32(mirror_coin.name()),
        bytes32(launcher_id_2),
        uint64(mirror_coin.amount),
        [b"foo", b"bar"],
        True,
        wallet_environments.full_node.full_node.blockchain.get_peak_height(),
    )
    await time_out_assert(15, dl_wallet_1.get_mirrors_for_launcher, [mirror], launcher_id_2)
    await time_out_assert(
        15, dl_wallet_2.get_mirrors_for_launcher, [dataclasses.replace(mirror, ours=False)], launcher_id_2
    )

    fee = uint64(2_000_000_000_000)

    async with dl_wallet_1.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await dl_wallet_1.delete_mirror(mirror.coin_id, peer_1, action_scope, fee=fee)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee + mirror.amount,
                        # these match exactly because of our change from the creation
                        "<=#spendable_balance": -fee + mirror.amount,
                        "<=#max_send_amount": -fee + mirror.amount,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 2,
                    },
                    "dl": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee + mirror.amount,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -2,
                    },
                    "dl": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
        ]
    )

    await time_out_assert(15, dl_wallet_1.get_mirrors_for_launcher, [], launcher_id_2)
    await time_out_assert(15, dl_wallet_2.get_mirrors_for_launcher, [], launcher_id_2)


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "reuse_puzhash": True,
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_datalayer_reorgs(wallet_environments: WalletTestFramework) -> None:
    # Setup
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    env = wallet_environments.environments[0]
    wallet_node = wallet_environments.environments[0].node

    # Define wallet aliases
    env.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }

    async with env.wallet_state_manager.lock:
        dl_wallet = await DataLayerWallet.create_new_dl_wallet(env.wallet_state_manager)

    async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        launcher_id = await dl_wallet.generate_new_reporter(bytes32.zeros, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {"init": True},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32.zeros)

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    await time_out_assert(15, is_singleton_confirmed_and_root, False, dl_wallet, launcher_id, bytes32.zeros)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 1,  # confirmed balance comes back
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {"unspent_coin_count": -1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32.zeros)

    async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dl_wallet.create_update_state_spend(launcher_id, bytes32([2] * 32), action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": -1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32([2] * 32))

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    await time_out_assert(15, is_singleton_confirmed_and_root, False, dl_wallet, launcher_id, bytes32.zeros)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": -1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32([2] * 32))

    async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dl_wallet.create_new_mirror(launcher_id, uint64(0), [b"foo", b"bar"], action_scope)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {},
                },
                post_block_balance_updates={
                    "xch": {
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    assert len(await dl_wallet.get_mirrors_for_launcher(launcher_id)) == 1

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    assert len(await dl_wallet.get_mirrors_for_launcher(launcher_id)) == 0

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {"unspent_coin_count": -1},
                },
                post_block_balance_updates={
                    "xch": {
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    assert len(await dl_wallet.get_mirrors_for_launcher(launcher_id)) == 1
