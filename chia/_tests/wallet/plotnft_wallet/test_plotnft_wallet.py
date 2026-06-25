from __future__ import annotations

import dataclasses
import re
from unittest.mock import Mock

import pytest
from chia_rs import G1Element
from chia_rs.chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.pools.plotnft_drivers import PlotNFT, PoolConfig, UserConfig
from chia.rpc.rpc_client import ResponseFailureError
from chia.simulator.simulator_protocol import ReorgProtocol
from chia.types.blockchain_format.program import Program
from chia.types.peer_info import PeerInfo
from chia.wallet.plotnft_wallet.plotnft_wallet import PlotNFT2Wallet
from chia.wallet.wallet_action_scope import PlotNFTTargetStateInfo
from chia.wallet.wallet_request_types import (
    PushTX,
    PWAbsorbRewards,
    PWJoinPool,
    PWSelfPool,
    PWStatus,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


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
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_plotnft_lifecycle(wallet_environments: WalletTestFramework, self_hostname: str) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "plotnft": 2,
    }

    POOL_REWARD_AMOUNT = uint64(1_750_000_000_000)

    # CREATION
    creation_fee = POOL_REWARD_AMOUNT + 1
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await PlotNFT2Wallet.create_new(
            wallet_state_manager=env.wallet_state_manager,
            xch_wallet=env.xch_wallet,
            action_scope=action_scope,
            fee=uint64(creation_fee),
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(creation_fee + 1),
                        "<=#spendable_balance": -(creation_fee + 1),
                        "<=#max_send_amount": -(creation_fee + 1),
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(creation_fee + 1),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {"init": True, "unspent_coin_count": 1},
                },
            )
        ]
    )

    plotnft_wallet = env.wallet_state_manager.get_wallet(
        uint32(env.wallet_aliases["plotnft"]), required_type=PlotNFT2Wallet
    )

    # Reorg (creation)
    height = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert height is not None
    await wallet_environments.full_node.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": creation_fee + 1,
                        "<=#spendable_balance": creation_fee + 1,
                        "<=#max_send_amount": creation_fee + 1,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                        ">=#unspent_coin_count": 0,
                    },
                    "plotnft": {"unspent_coin_count": -1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(creation_fee + 1),
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {"unspent_coin_count": 1},
                },
            )
        ]
    )

    # (check an error)
    with pytest.raises(
        ValueError,
        match=re.escape("`leave_pool` called on a non-pooling or exiting PlotNFT"),
    ):
        async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
            await plotnft_wallet.leave_pool(action_scope=action_scope)

    # REWARDS GENERATED
    NUM_REWARDS_FARMED = 2
    REWARDS_GAINED = POOL_REWARD_AMOUNT * NUM_REWARDS_FARMED
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=NUM_REWARDS_FARMED,
        farm_to=plotnft_wallet.p2_singleton_puzzle_hash,
        guarantee_transaction_blocks=True,
    )
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=1)
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await env.change_balances(
        {
            "plotnft": {
                "confirmed_wallet_balance": REWARDS_GAINED,
                "unconfirmed_wallet_balance": REWARDS_GAINED,
                "max_send_amount": REWARDS_GAINED,
                "spendable_balance": REWARDS_GAINED,
                "unspent_coin_count": NUM_REWARDS_FARMED,
            }
        }
    )
    await env.check_balances()

    # Reorg (rewards generated)
    height = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert height is not None
    await wallet_environments.full_node.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 3), uint32(height + 1), bytes32.zeros, None)
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await env.change_balances(
        {
            "plotnft": {
                "confirmed_wallet_balance": -REWARDS_GAINED,
                "unconfirmed_wallet_balance": -REWARDS_GAINED,
                "max_send_amount": -REWARDS_GAINED,
                "spendable_balance": -REWARDS_GAINED,
                "unspent_coin_count": -NUM_REWARDS_FARMED,
            }
        }
    )
    await env.check_balances()
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=NUM_REWARDS_FARMED,
        farm_to=plotnft_wallet.p2_singleton_puzzle_hash,
        guarantee_transaction_blocks=True,
    )
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=1)
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await env.change_balances(
        {
            "plotnft": {
                "confirmed_wallet_balance": REWARDS_GAINED,
                "unconfirmed_wallet_balance": REWARDS_GAINED,
                "max_send_amount": REWARDS_GAINED,
                "spendable_balance": REWARDS_GAINED,
                "unspent_coin_count": NUM_REWARDS_FARMED,
            }
        }
    )
    await env.check_balances()
    # check a branch of `get_unconfirmed_balance` (no records specified)
    assert await plotnft_wallet.get_unconfirmed_balance() == REWARDS_GAINED

    # CLAIM REWARDS
    amount_to_succeed_in_claiming = 100
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        with pytest.raises(ValueError, match="Fee is greater than the total amount of rewards"):
            await plotnft_wallet.claim_rewards(
                action_scope=action_scope,
                fee=uint64(REWARDS_GAINED + 1),
            )
        await plotnft_wallet.claim_rewards(
            action_scope=action_scope,
            fee=uint64(REWARDS_GAINED - amount_to_succeed_in_claiming),
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "plotnft": {
                        "unconfirmed_wallet_balance": -REWARDS_GAINED,
                        "spendable_balance": -REWARDS_GAINED,
                        "max_send_amount": -REWARDS_GAINED,
                        "pending_coin_removal_count": NUM_REWARDS_FARMED + 1,
                    }
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": amount_to_succeed_in_claiming,
                        "unconfirmed_wallet_balance": amount_to_succeed_in_claiming,
                        "spendable_balance": amount_to_succeed_in_claiming,
                        "max_send_amount": amount_to_succeed_in_claiming,
                        "unspent_coin_count": 1,
                    },
                    "plotnft": {
                        "confirmed_wallet_balance": -REWARDS_GAINED,
                        "pending_coin_removal_count": -NUM_REWARDS_FARMED - 1,
                        "unspent_coin_count": -NUM_REWARDS_FARMED,
                    },
                },
            )
        ]
    )

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        with pytest.raises(
            ValueError,
            match=re.escape("No rewards to claim"),
        ):
            await plotnft_wallet.claim_rewards(action_scope=action_scope)

    # Reorg (claim rewards)
    height = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert height is not None
    await wallet_environments.full_node.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -amount_to_succeed_in_claiming,
                        "unconfirmed_wallet_balance": -amount_to_succeed_in_claiming,
                        "spendable_balance": -amount_to_succeed_in_claiming,
                        "max_send_amount": -amount_to_succeed_in_claiming,
                        "unspent_coin_count": -1,
                    },
                    "plotnft": {
                        "confirmed_wallet_balance": REWARDS_GAINED,
                        "pending_coin_removal_count": NUM_REWARDS_FARMED + 1,
                        "unspent_coin_count": NUM_REWARDS_FARMED,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": amount_to_succeed_in_claiming,
                        "unconfirmed_wallet_balance": amount_to_succeed_in_claiming,
                        "spendable_balance": amount_to_succeed_in_claiming,
                        "max_send_amount": amount_to_succeed_in_claiming,
                        "unspent_coin_count": 1,
                    },
                    "plotnft": {
                        "confirmed_wallet_balance": -REWARDS_GAINED,
                        "pending_coin_removal_count": -NUM_REWARDS_FARMED - 1,
                        "unspent_coin_count": -NUM_REWARDS_FARMED,
                    },
                },
            )
        ]
    )

    # JOIN POOL
    joining_fee = uint64(1_000)

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await plotnft_wallet.join_pool(
            pool_config=PoolConfig(
                pool_puzzle_hash=bytes32.zeros,
                heightlock=uint32(5),
                pool_memoization=Program.to(None),
            ),
            pool_url="https://daurl.com",
            action_scope=action_scope,
            fee=joining_fee,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -joining_fee,
                        "<=#spendable_balance": -joining_fee,
                        "<=#max_send_amount": -joining_fee,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                    },
                    "plotnft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -joining_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {"pending_coin_removal_count": -1},
                },
            )
        ]
    )
    assert (
        await env.wallet_state_manager.plotnft2_store.get_latest_remark(plotnft_wallet.plotnft_id)
        == "https://daurl.com"
    )

    # Reorg (join pool)
    height = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert height is not None
    await wallet_environments.full_node.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": joining_fee,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                        ">=#unspent_coin_count": 0,
                    },
                    "plotnft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -joining_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {"pending_coin_removal_count": -1},
                },
            )
        ]
    )

    # RECEIVE REWARDS (while pooling)
    EXTRA_POOLING_REWARDS = 2
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=NUM_REWARDS_FARMED + EXTRA_POOLING_REWARDS,
        farm_to=plotnft_wallet.p2_singleton_puzzle_hash,
        guarantee_transaction_blocks=True,
    )
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=1)

    await wallet_environments.full_node.wait_for_wallet_synced(env.node)
    await env.change_balances(
        {
            "plotnft": {
                "confirmed_wallet_balance": REWARDS_GAINED + POOL_REWARD_AMOUNT * EXTRA_POOLING_REWARDS,
                "unconfirmed_wallet_balance": REWARDS_GAINED + POOL_REWARD_AMOUNT * EXTRA_POOLING_REWARDS,
                "max_send_amount": REWARDS_GAINED + POOL_REWARD_AMOUNT * EXTRA_POOLING_REWARDS,
                "spendable_balance": REWARDS_GAINED + POOL_REWARD_AMOUNT * EXTRA_POOLING_REWARDS,
                "unspent_coin_count": NUM_REWARDS_FARMED + EXTRA_POOLING_REWARDS,
            }
        }
    )
    await env.check_balances()

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        with pytest.raises(
            ValueError,
            match=re.escape("Cannot claim rewards while pooling. If you're a pool, try `forward_pool_rewards`"),
        ):
            await plotnft_wallet.claim_rewards(action_scope=action_scope)

    # LOSE REWARDS (while pooling)
    pool_rewards = await env.wallet_state_manager.plotnft2_store.get_pool_rewards(plotnft_id=plotnft_wallet.plotnft_id)
    plotnft = await plotnft_wallet.get_current_plotnft()
    coin_spends = []
    singleton_coin_spend = None
    for reward in pool_rewards[0:-1]:
        new_coin_spends = plotnft.forward_pool_reward(reward)
        coin_spends += new_coin_spends
        singleton_coin_spend = next(iter(spend for spend in new_coin_spends if spend.coin.amount == 1))
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=singleton_coin_spend,
            genesis_challenge=None,
            pre_uncurry=None,
            previous_plotnft_puzzle=plotnft,
        )

    NUM_CLAIMED = len(pool_rewards) - 1
    await wallet_environments.full_node_rpc_client.push_tx(WalletSpendBundle(coin_spends, G2Element()))

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "plotnft": {
                        "confirmed_wallet_balance": -POOL_REWARD_AMOUNT * NUM_CLAIMED,
                        "unconfirmed_wallet_balance": -POOL_REWARD_AMOUNT * NUM_CLAIMED,
                        "max_send_amount": -POOL_REWARD_AMOUNT * NUM_CLAIMED,
                        "spendable_balance": -POOL_REWARD_AMOUNT * NUM_CLAIMED,
                        "unspent_coin_count": -NUM_CLAIMED,
                    }
                },
            )
        ]
    )

    # LEAVE POOL (to another)
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        finish_leaving_fee = uint64(1_000_000_000)
        await plotnft_wallet.join_pool(
            action_scope=action_scope,
            fee=uint64(0),
            finish_leaving_fee=finish_leaving_fee,
            pool_url="https://daurl2.com",
            pool_config=PoolConfig(
                pool_puzzle_hash=bytes32.zeros,
                heightlock=uint32(5),
                pool_memoization=Program.to(None),
            ),
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "plotnft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {},
                    "plotnft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    # (check an error)
    with pytest.raises(
        ValueError,
        match=re.escape("`leave_pool` called on a non-pooling or exiting PlotNFT"),
    ):
        async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
            await plotnft_wallet.leave_pool(action_scope=action_scope)

    # Reorg (leave pool to another)
    height = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert height is not None
    await wallet_environments.full_node.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "plotnft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {},
                    "plotnft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    # FINISH LEAVING (to new pool)
    plotnft = await plotnft_wallet.get_current_plotnft()
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=plotnft.guaranteed_pool_config.heightlock + 2,
        guarantee_transaction_blocks=True,
    )

    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -finish_leaving_fee,
                        "<=#spendable_balance": -finish_leaving_fee,
                        "<=#max_send_amount": -finish_leaving_fee,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": 2,  # one for the exit, one for the join
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -finish_leaving_fee,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": -2,
                    },
                },
            )
        ]
    )

    # LEAVE POOL
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        leave_fee = uint64(1_000_000)
        finish_leaving_fee = uint64(1_000_000_000)
        await plotnft_wallet.leave_pool(
            action_scope=action_scope,
            fee=leave_fee,
            finish_leaving_fee=finish_leaving_fee,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -leave_fee,
                        "<=#spendable_balance": -leave_fee,
                        "<=#max_send_amount": -leave_fee,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -leave_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        with pytest.raises(
            ValueError,
            match=re.escape("Cannot claim rewards while pooling. If you're a pool, try `forward_pool_rewards`"),
        ):
            await plotnft_wallet.claim_rewards(action_scope=action_scope)

    # Reorg (leave pool)
    height = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert height is not None
    await wallet_environments.full_node.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": leave_fee,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                        ">=#unspent_coin_count": 0,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -leave_fee,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    # LOSE REWARDS (while leaving)
    plotnft = await plotnft_wallet.get_current_plotnft()
    [pool_reward] = await env.wallet_state_manager.plotnft2_store.get_pool_rewards(plotnft_id=plotnft_wallet.plotnft_id)
    coin_spends = plotnft.forward_pool_reward(pool_reward)
    await env.rpc_client.push_tx(PushTX(spend_bundle=WalletSpendBundle(coin_spends, G2Element())))

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "plotnft": {
                        "confirmed_wallet_balance": -POOL_REWARD_AMOUNT,
                        "unconfirmed_wallet_balance": -POOL_REWARD_AMOUNT,
                        "max_send_amount": -POOL_REWARD_AMOUNT,
                        "spendable_balance": -POOL_REWARD_AMOUNT,
                        "unspent_coin_count": -1,
                    }
                },
            )
        ]
    )

    # FINISH LEAVING
    plotnft = await plotnft_wallet.get_current_plotnft()
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=plotnft.guaranteed_pool_config.heightlock + 2,
        guarantee_transaction_blocks=True,
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -finish_leaving_fee,
                        "<=#spendable_balance": -finish_leaving_fee,
                        "<=#max_send_amount": -finish_leaving_fee,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -finish_leaving_fee,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    # Reorg (finish leaving)
    height = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert height is not None
    await wallet_environments.full_node.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": finish_leaving_fee,
                        "<=#spendable_balance": 0,
                        "<=#max_send_amount": 0,
                        ">=#pending_change": 0,
                        ">=#pending_coin_removal_count": 1,
                        ">=#unspent_coin_count": 0,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -finish_leaving_fee,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "<=#pending_change": 0,
                        "<=#pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    },
                    "plotnft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    # Resync start
    env.node._close()
    await env.node._await_closed()
    env.node.config["database_path"] = "wallet/db/blockchain_wallet_v2_test1_CHALLENGE_KEY.sqlite"

    # use second node to start the same wallet, reusing config
    await env.node._start()
    await env.peer_server.start_client(
        PeerInfo(self_hostname, wallet_environments.full_node.full_node.server.get_port()),
        None,
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)
    await wallet_environments.process_pending_states([WalletStateTransition(), WalletStateTransition()])

    rediscovered_plotnft_wallet = env.node.wallet_state_manager.wallets[uint32(env.wallet_aliases["plotnft"])]
    assert isinstance(rediscovered_plotnft_wallet, PlotNFT2Wallet)
    rediscovered_plotnft = await rediscovered_plotnft_wallet.get_current_plotnft()

    # and test just a normal restart
    env.node._close()
    await env.node._await_closed()
    await env.node._start()
    await env.peer_server.start_client(
        PeerInfo(self_hostname, wallet_environments.full_node.full_node.server.get_port()),
        None,
    )
    env.node.config["selected_network"] = "simulator"
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)
    rediscovered_plotnft_wallet = env.node.wallet_state_manager.wallets[uint32(env.wallet_aliases["plotnft"])]
    assert isinstance(rediscovered_plotnft_wallet, PlotNFT2Wallet)
    assert await rediscovered_plotnft_wallet.get_current_plotnft() == rediscovered_plotnft


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
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_plotnft_errors(wallet_environments: WalletTestFramework, self_hostname: str) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "plotnft": 2,
    }

    # creation error
    with pytest.raises(ValueError, match="pool_url and pool_config must be both None or both not None"):
        async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
            await PlotNFT2Wallet.create_new(
                wallet_state_manager=env.wallet_state_manager,
                xch_wallet=env.xch_wallet,
                action_scope=action_scope,
                fee=uint64(0),
                pool_config=None,
                pool_url="https://daurl.com",
            )
    with pytest.raises(ValueError, match="pool_url and pool_config must be both None or both not None"):
        async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
            await PlotNFT2Wallet.create_new(
                wallet_state_manager=env.wallet_state_manager,
                xch_wallet=env.xch_wallet,
                action_scope=action_scope,
                fee=uint64(0),
                pool_config=PoolConfig(
                    pool_puzzle_hash=bytes32.zeros,
                    heightlock=uint32(5),
                    pool_memoization=Program.to(None),
                ),
                pool_url=None,
            )

    # create to pool
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await PlotNFT2Wallet.create_new(
            wallet_state_manager=env.wallet_state_manager,
            xch_wallet=env.xch_wallet,
            action_scope=action_scope,
            fee=uint64(0),
            pool_config=PoolConfig(
                pool_puzzle_hash=bytes32.zeros,
                heightlock=uint32(5),
                pool_memoization=Program.to(None),
            ),
            pool_url="https://daurl.com",
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={"xch": {"set_remainder": True}},
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "plotnft": {"init": True, "set_remainder": True},
                },
            )
        ]
    )

    plotnft_wallet = env.wallet_state_manager.wallets[uint32(env.wallet_aliases["plotnft"])]
    assert isinstance(plotnft_wallet, PlotNFT2Wallet)
    # check a quick DB error
    with pytest.raises(ValueError, match="coin_ids must not be empty"):
        await env.wallet_state_manager.plotnft2_store.get_plotnfts(coin_ids=[])

    # check a different DB error
    with pytest.raises(ValueError, match="not found in PlotNFTStore"):
        await env.wallet_state_manager.plotnft2_store.get_plotnft_created_height(coin_id=bytes32.zeros)

    # check an RPC error
    with pytest.raises(
        ResponseFailureError,
        match=re.escape("`pw_self_pool` called on a non-pooling wallet"),
    ):
        await env.rpc_client.pw_self_pool(
            request=PWSelfPool(wallet_id=uint32(1)),
            tx_config=wallet_environments.tx_config,
        )

    # some `leave_pool` argument checks
    with pytest.raises(
        ValueError,
        match="Both new_pool_url or new_pool_config must be provided together",
    ):
        await plotnft_wallet.leave_pool(
            action_scope=action_scope,
            new_pool_url=None,
            new_pool_config=PoolConfig(
                pool_puzzle_hash=bytes32.zeros,
                heightlock=uint32(5),
                pool_memoization=Program.to(None),
            ),
        )
    with pytest.raises(
        ValueError,
        match="Both new_pool_url or new_pool_config must be provided together",
    ):
        await plotnft_wallet.leave_pool(
            action_scope=action_scope,
            new_pool_url="https://daurl2.com",
            new_pool_config=None,
        )

    # try to leave and delete necessary info while leaving to make sure wallet still leaves (with no fee and no pool)
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        finish_leaving_fee = uint64(1_000_000_000)
        await plotnft_wallet.leave_pool(
            action_scope=action_scope,
            fee=uint64(0),
            finish_leaving_fee=finish_leaving_fee,
            new_pool_url="https://daurl2.com",
            new_pool_config=PoolConfig(
                pool_puzzle_hash=bytes32.zeros,
                heightlock=uint32(5),
                pool_memoization=Program.to(None),
            ),
        )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "plotnft": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "plotnft": {"set_remainder": True},
                },
            )
        ]
    )

    # deleting the finish_exiting_info so the wallet has to adapt and try just leave with no fee
    async with env.wallet_state_manager.plotnft2_store.db_wrapper.writer_maybe_transaction() as conn:
        await conn.execute(
            "DELETE FROM finish_exiting_info WHERE wallet_id = ?",
            (plotnft_wallet.id(),),
        )

    # also adding an unconfirmed transaction to test that completion is not attempted when state is uncertain
    await env.wallet_state_manager.add_transaction(
        env.wallet_state_manager.new_outgoing_transaction(
            wallet_id=plotnft_wallet.id(),
            puzzle_hash=bytes32.zeros,
            amount=uint64(0),
            fee=uint64(0),
            spend_bundle=WalletSpendBundle([], G2Element()),
            additions=[],
            removals=[],
            name=bytes32.zeros,
        )
    )

    # farm to where completion should happen
    plotnft = await plotnft_wallet.get_current_plotnft()
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=plotnft.guaranteed_pool_config.heightlock + 2,
        guarantee_transaction_blocks=True,
    )

    await wallet_environments.full_node.wait_for_wallet_synced(env.node)
    # make sure nothing happens
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={"xch": {}, "plotnft": {}},
                post_block_balance_updates={"xch": {}, "plotnft": {}},
            )
        ],
        invalid_transactions=[bytes32.zeros],
    )
    # delete the tx_record
    async with env.wallet_state_manager.tx_store.db_wrapper.writer_maybe_transaction() as conn:
        await conn.execute("DELETE FROM transaction_record WHERE bundle_id = ?", (bytes32.zeros,))
        env.wallet_state_manager.tx_store.unconfirmed_txs = [
            tx for tx in env.wallet_state_manager.tx_store.unconfirmed_txs if tx.name != bytes32.zeros
        ]
    # farm a block to re-trigger new_peak
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "plotnft": {
                        "pending_coin_removal_count": 1,  # only one, because no join
                    },
                },
                post_block_balance_updates={
                    "xch": {},
                    "plotnft": {
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )

    # check a `join_pool` argument check
    with pytest.raises(
        ValueError,
        match="A fee to finish leaving was specified but PlotNFT does not need to leave",
    ):
        await plotnft_wallet.join_pool(
            action_scope=action_scope,
            pool_config=PoolConfig(
                pool_puzzle_hash=bytes32.zeros,
                heightlock=uint32(5),
                pool_memoization=Program.to(None),
            ),
            pool_url="https://daurl.com",
            finish_leaving_fee=uint64(1),
        )

    # check a `coin_added` type guard
    plotnft = await plotnft_wallet.get_current_plotnft()
    with pytest.raises(ValueError, match="No index found for synthetic pubkey"):
        await plotnft_wallet.coin_added(
            coin=Mock(),
            height=uint32(0),
            peer=Mock(),
            coin_data=PlotNFT(
                launcher_id=bytes32.zeros,
                genesis_challenge=bytes32.zeros,
                user_config=UserConfig(synthetic_pubkey=G1Element()),  # the important bit
                exiting=False,
                coin=Mock(),
                singleton_lineage_proof=Mock(),
            ),
        )
    plotnft_after_raise = await plotnft_wallet.get_current_plotnft()
    assert plotnft_after_raise == plotnft

    # check a __post_init__
    target_state = PlotNFTTargetStateInfo(
        wallet_id=plotnft_wallet.id(),
        exiting_fee=uint64(0),
        next_pool_url="blah",
        next_pool_puzzle_hash=bytes32.zeros,
        next_heightlock=uint32(0),
        next_pool_memoization=Program.to(None),
    )
    for field_name in (
        "next_pool_url",
        "next_pool_puzzle_hash",
        "next_heightlock",
        "next_pool_memoization",
    ):
        with pytest.raises(
            ValueError,
            match="Error initializing next PlotNFT target state, not all options for join were specified",
        ):
            dataclasses.replace(target_state, **{field_name: None})  # type: ignore[arg-type]

    # check some RPC errors
    with pytest.raises(ResponseFailureError, match="Pool memoization is required for PlotNFT2Wallet"):
        await env.rpc_client.pw_join_pool(
            request=PWJoinPool(
                wallet_id=plotnft_wallet.id(),
                pool_url="",
                target_puzzlehash=bytes32.zeros,
                relative_lock_height=uint32(0),
            ),
            tx_config=wallet_environments.tx_config,
        )

    with pytest.raises(
        ResponseFailureError,
        match=re.escape("`pw_join_pool` called on a non-pooling wallet"),
    ):
        await env.rpc_client.pw_join_pool(
            request=PWJoinPool(
                wallet_id=uint32(1),
                pool_url="",
                target_puzzlehash=bytes32.zeros,
                relative_lock_height=uint32(0),
                pool_memoization=Program.to(None),
            ),
            tx_config=wallet_environments.tx_config,
        )

    with pytest.raises(
        ResponseFailureError,
        match=re.escape("`pw_absorb_rewards` called on a non-pooling wallet"),
    ):
        await env.rpc_client.pw_absorb_rewards(
            request=PWAbsorbRewards(wallet_id=uint32(1)),
            tx_config=wallet_environments.tx_config,
        )

    with pytest.raises(
        ResponseFailureError,
        match=re.escape("`pw_status` called on a non-pooling wallet"),
    ):
        await env.rpc_client.pw_status(request=PWStatus(wallet_id=uint32(1)))
