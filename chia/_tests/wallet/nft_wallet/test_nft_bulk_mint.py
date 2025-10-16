from __future__ import annotations

from typing import Optional, cast

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import Program
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.address_type import AddressType
from chia.wallet.wallet_request_types import NFTGetNFTs, NFTMintBulk, NFTMintMetadata, PushTransactions, SelectCoins


async def nft_count(wallet: NFTWallet) -> int:
    return await wallet.get_nft_count()


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("with_did", [True, False])
@pytest.mark.anyio
async def test_nft_mint(wallet_environments: WalletTestFramework, with_did: bool) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_0 = env_0.xch_wallet
    wallet_1 = env_1.xch_wallet
    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    async with wallet_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph_0 = await action_scope.get_puzzle_hash(env_0.wallet_state_manager)
        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_0.wallet_state_manager, wallet_0, uint64(1), action_scope
        )

    hex_did_id = did_wallet.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)

    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_0, name="NFT WALLET 1", did_id=did_id
    )

    nft_wallet_1 = await NFTWallet.create_new_nft_wallet(env_1.wallet_state_manager, wallet_1, name="NFT WALLET 2")

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                    "nft": {
                        "init": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft": {
                        "init": True,
                    }
                },
                post_block_balance_updates={},
            ),
        ]
    )

    royalty_pc = uint16(300)
    royalty_addr = ph_0

    mint_total = 10
    fee = uint64(100)
    metadata_list = [
        {
            "program": Program.to(
                [("u", ["https://www.chia.net/img/branding/chia-logo.svg"]), ("h", bytes32.zeros.hex())]
            ),
            "royalty_pc": royalty_pc,
            "royalty_ph": royalty_addr,
        }
        for x in range(mint_total)
    ]

    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        target_list = [await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager) for x in range(mint_total)]

    async with nft_wallet_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        if with_did:
            await nft_wallet_0.mint_from_did(
                metadata_list,
                action_scope,
                target_list=target_list,
                mint_number_start=1,
                mint_total=mint_total,
                fee=fee,
            )
        else:
            await nft_wallet_0.mint_from_xch(
                metadata_list,
                action_scope,
                target_list=target_list,
                mint_number_start=1,
                mint_total=mint_total,
                fee=fee,
            )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee - mint_total,
                        "<=#spendable_balance": -fee - mint_total,
                        "<=#max_send_amount": -fee - mint_total,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "max_send_amount": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                    }
                    if with_did
                    else {},
                    "nft": {
                        "pending_coin_removal_count": mint_total,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee - mint_total,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "max_send_amount": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                    }
                    if with_did
                    else {},
                    "nft": {
                        "pending_coin_removal_count": -mint_total,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "nft": {
                        "unspent_coin_count": mint_total,
                    }
                },
            ),
        ]
    )

    nfts = await nft_wallet_1.get_current_nfts()
    matched_data = dict(zip(target_list, metadata_list))

    # Check targets and metadata entries match in the final nfts
    for nft in nfts:
        mod, args = nft.full_puzzle.uncurry()
        unft = UncurriedNFT.uncurry(mod, args)
        assert isinstance(unft, UncurriedNFT)
        inner_args = unft.inner_puzzle.uncurry()[1]
        inner_ph = inner_args.at("rrrf").get_tree_hash()
        meta = unft.metadata.at("rfr").as_atom()
        # check that the target puzzle hashes of transferred nfts matches the metadata entry
        prog: Program = cast(Program, matched_data[inner_ph]["program"])
        assert prog.at("rfr").as_atom() == meta
        if with_did:
            # Check the did is set for each nft
            assert nft.minter_did == did_id
        else:
            assert nft.minter_did is None


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("zero_royalties", [True, False])
@pytest.mark.parametrize("with_did", [True, False])
@pytest.mark.anyio
async def test_nft_mint_rpc(wallet_environments: WalletTestFramework, zero_royalties: bool, with_did: bool) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_0 = env_0.xch_wallet
    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    async with env_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph_1 = await action_scope.get_puzzle_hash(env_1.wallet_state_manager)

    async with env_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_0.wallet_state_manager, wallet_0, uint64(1), action_scope
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    hex_did_id = did_wallet_maker.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(env_0.node.config))

    nft_wallet_maker = await env_0.rpc_client.create_new_nft_wallet(name="NFT WALLET 1", did_id=hmr_did_id)

    await env_1.rpc_client.create_new_nft_wallet(name="NFT WALLET 2", did_id=None)

    await env_0.change_balances({"nft": {"init": True}})
    await env_1.change_balances({"nft": {"init": True}})

    n = 10
    chunk = 5
    metadata_list = [
        {
            "hash": bytes([i] * 32).hex(),
            "uris": [f"https://data.com/{i}"],
            "meta_hash": bytes([i] * 32).hex(),
            "meta_uris": [f"https://meatadata.com/{i}"],
            "license_hash": bytes([i] * 32).hex(),
            "license_uris": [f"https://license.com/{i}"],
            "edition_number": i + 1,
            "edition_total": n,
        }
        for i in range(n)
    ]
    target_list = [encode_puzzle_hash(ph_1, "xch") for x in range(n)]
    royalty_address = None if zero_royalties else encode_puzzle_hash(bytes32.zeros, "xch")
    royalty_percentage = None if zero_royalties else 300
    fee = 100
    num_chunks = int(n / chunk) + (1 if n % chunk > 0 else 0)
    required_amount = n + (fee * num_chunks)
    select_coins_response = await env_0.rpc_client.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(required_amount),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config,
            wallet_id=wallet_0.id(),
        )
    )
    funding_coin = select_coins_response.coins[0]
    assert funding_coin.amount >= required_amount
    next_coin = funding_coin
    did_coin = (
        await env_0.rpc_client.select_coins(
            SelectCoins.from_coin_selection_config(
                amount=uint64(1),
                coin_selection_config=wallet_environments.tx_config.coin_selection_config,
                wallet_id=uint32(env_0.wallet_aliases["did"]),
            )
        )
    ).coins[0]
    did_lineage_parent: Optional[bytes32] = None
    txs: list[TransactionRecord] = []
    nft_ids = set()
    for i in range(0, n, chunk):
        resp = await env_0.rpc_client.nft_mint_bulk(
            NFTMintBulk(
                wallet_id=nft_wallet_maker["wallet_id"],
                metadata_list=[NFTMintMetadata.from_json_dict(metadata) for metadata in metadata_list[i : i + chunk]],
                target_list=target_list[i : i + chunk],
                royalty_percentage=uint16.construct_optional(royalty_percentage),
                royalty_address=royalty_address,
                mint_number_start=uint16(i + 1),
                mint_total=uint16(n),
                xch_coins=[next_coin],
                xch_change_target=funding_coin.puzzle_hash.hex(),
                did_coin=did_coin if with_did else None,
                did_lineage_parent=did_lineage_parent if with_did else None,
                mint_from_did=with_did,
                fee=uint64(fee),
            ),
            tx_config=wallet_environments.tx_config,
        )
        if with_did:
            did_lineage_parent = next(
                cn
                for tx in resp.transactions
                if tx.spend_bundle is not None
                for cn in tx.spend_bundle.removals()
                if cn.name() == did_coin.name()
            ).parent_coin_info
            did_coin = next(
                cn
                for tx in resp.transactions
                if tx.spend_bundle is not None
                for cn in tx.spend_bundle.additions()
                if (cn.parent_coin_info == did_coin.name()) and (cn.amount == 1)
            )
        txs.extend(resp.transactions)
        xch_adds = [
            c
            for tx in resp.transactions
            if tx.spend_bundle is not None
            for c in tx.spend_bundle.additions()
            if c.puzzle_hash == funding_coin.puzzle_hash
        ]
        assert len(xch_adds) == 1
        next_coin = xch_adds[0]
        for nft_id in resp.nft_id_list:
            nft_ids.add(decode_puzzle_hash(nft_id))

    await env_0.rpc_client.push_transactions(PushTransactions(transactions=txs), wallet_environments.tx_config)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -(fee * num_chunks) - n,
                        "<=#spendable_balance": -(fee * num_chunks) - n,
                        "<=#max_send_amount": -(fee * num_chunks) - n,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": num_chunks,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "max_send_amount": -1,
                        # 2 here feels a bit weird but I'm not sure it's necessarily incorrect
                        "pending_change": 2,
                        "pending_coin_removal_count": 2,
                    }
                    if with_did
                    else {},
                    "nft": {
                        "pending_coin_removal_count": n,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -(fee * num_chunks) - n,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -num_chunks,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "max_send_amount": 1,
                        "pending_change": -2,
                        "pending_coin_removal_count": -2,
                    }
                    if with_did
                    else {},
                    "nft": {
                        "pending_coin_removal_count": -n,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "nft": {
                        "unspent_coin_count": n,
                    }
                },
            ),
        ]
    )

    # check NFT edition numbers
    nfts = [nft for nft in (await env_1.rpc_client.list_nfts(NFTGetNFTs(uint32(env_1.wallet_aliases["nft"])))).nft_list]
    for nft in nfts:
        edition_num = nft.edition_number
        meta_dict = metadata_list[edition_num - 1]
        assert meta_dict["hash"] == nft.data_hash.hex()
        assert meta_dict["uris"] == nft.data_uris
        assert meta_dict["meta_hash"] == nft.metadata_hash.hex()
        assert meta_dict["meta_uris"] == nft.metadata_uris
        assert meta_dict["license_hash"] == nft.license_hash.hex()
        assert meta_dict["license_uris"] == nft.license_uris
        assert meta_dict["edition_number"] == nft.edition_number
        assert meta_dict["edition_total"] == nft.edition_total
        assert nft.launcher_id in nft_ids


@pytest.mark.limit_consensus_modes
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.parametrize("with_did", [True, False])
@pytest.mark.anyio
async def test_nft_mint_multiple_xch(wallet_environments: WalletTestFramework, with_did: bool) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_0 = env_0.xch_wallet
    wallet_1 = env_1.xch_wallet
    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    async with env_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph_0 = await action_scope.get_puzzle_hash(env_0.wallet_state_manager)
        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            env_0.wallet_state_manager, wallet_0, uint64(1), action_scope
        )
    async with env_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph_1 = await action_scope.get_puzzle_hash(env_1.wallet_state_manager)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "init": True,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    hex_did_id = did_wallet.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)

    await time_out_assert(5, did_wallet.get_confirmed_balance, 1)

    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        env_0.wallet_state_manager, wallet_0, name="NFT WALLET 1", did_id=did_id
    )

    await NFTWallet.create_new_nft_wallet(wallet_1.wallet_state_manager, wallet_1, name="NFT WALLET 2")

    await env_0.change_balances({"nft": {"init": True}})
    await env_1.change_balances({"nft": {"init": True}})

    # construct sample metadata
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )
    royalty_pc = uint16(300)
    royalty_addr = ph_0

    mint_total = 1
    fee = uint64(100)
    metadata_list = [
        {"program": metadata, "royalty_pc": royalty_pc, "royalty_ph": royalty_addr} for x in range(mint_total)
    ]

    # Grab two coins for testing that we can create a bulk minting with more than 1 xch coin
    async with env_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=False) as action_scope:
        xch_coins_1 = await wallet_0.select_coins(amount=uint64(10000), action_scope=action_scope)
        xch_coins_2 = await wallet_0.select_coins(
            amount=uint64(10000),
            action_scope=action_scope,
        )
    xch_coins = xch_coins_1.union(xch_coins_2)

    target_list = [ph_1 for x in range(mint_total)]

    async with env_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        if with_did:
            await nft_wallet_0.mint_from_did(
                metadata_list,
                action_scope,
                target_list=target_list,
                mint_number_start=1,
                mint_total=mint_total,
                xch_coins=xch_coins,
                fee=fee,
            )
        else:
            await nft_wallet_0.mint_from_xch(
                metadata_list,
                action_scope,
                target_list=target_list,
                mint_number_start=1,
                mint_total=mint_total,
                xch_coins=xch_coins,
                fee=fee,
            )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee - mint_total,
                        "<=#spendable_balance": -fee - mint_total,
                        "<=#max_send_amount": -fee - mint_total,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 2,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "max_send_amount": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                    }
                    if with_did
                    else {},
                    "nft": {
                        "pending_coin_removal_count": mint_total,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee - mint_total,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -1,  # The two coins get combined for change
                    },
                    "did": {
                        "spendable_balance": 1,
                        "max_send_amount": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                    }
                    if with_did
                    else {},
                    "nft": {
                        "pending_coin_removal_count": -mint_total,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "nft": {
                        "unspent_coin_count": mint_total,
                    }
                },
            ),
        ]
    )
