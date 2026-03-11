from __future__ import annotations

import re

import pytest
from chia_rs.chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.pools.plotnft_drivers import PoolConfig
from chia.simulator.simulator_protocol import ReorgProtocol
from chia.types.blockchain_format.program import Program
from chia.types.peer_info import PeerInfo
from chia.wallet.plotnft_wallet.plotnft_wallet import PlotNFT2Wallet
from chia.wallet.wallet_request_types import PushTX
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

    # REWARDS GENERATED
    NUM_REWARDS_FARMED = 2
    REWARDS_GAINED = POOL_REWARD_AMOUNT * NUM_REWARDS_FARMED
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=NUM_REWARDS_FARMED, farm_to=plotnft_wallet.p2_singleton_puzzle_hash, guarantee_transaction_blocks=True
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
        count=NUM_REWARDS_FARMED, farm_to=plotnft_wallet.p2_singleton_puzzle_hash, guarantee_transaction_blocks=True
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
                pool_puzzle_hash=bytes32.zeros, heightlock=uint32(5), pool_memoization=Program.to(None)
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
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=NUM_REWARDS_FARMED, farm_to=plotnft_wallet.p2_singleton_puzzle_hash, guarantee_transaction_blocks=True
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

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        with pytest.raises(
            ValueError,
            match=re.escape("Cannot claim rewards while pooling. If you're a pool, try `forward_pool_rewards`"),
        ):
            await plotnft_wallet.claim_rewards(action_scope=action_scope)

    # LOSE REWARDS (while pooling)
    plotnft = await plotnft_wallet.get_current_plotnft()
    [pool_reward, _] = await env.wallet_state_manager.plotnft2_store.get_pool_rewards(
        plotnft_id=plotnft_wallet.plotnft_id
    )
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

    # LEAVE POOL
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        leave_fee = uint64(1_000_000)
        finish_leaving_fee = uint64(1_000_000_000)
        await plotnft_wallet.leave_pool(action_scope=action_scope, fee=leave_fee, finish_leaving_fee=finish_leaving_fee)

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
        count=plotnft.guaranteed_pool_config.heightlock + 2, guarantee_transaction_blocks=True
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

    # use second node to start the same wallet, reusing config and db
    await env.node._start()
    await env.peer_server.start_client(
        PeerInfo(self_hostname, wallet_environments.full_node.full_node.server.get_port()), None
    )
    await wallet_environments.full_node.wait_for_wallet_synced(env.node)
    await wallet_environments.process_pending_states([WalletStateTransition(), WalletStateTransition()])


# TODO: test halving
