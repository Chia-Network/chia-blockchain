from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, Literal

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64

from chia._tests.cmds.test_cmd_framework import check_click_parsing
from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import (
    WalletEnvironment,
    WalletStateTransition,
    WalletTestFramework,
)
from chia._tests.util.time_out_assert import time_out_assert_not_none
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.cmd_helpers import NeedsTXConfig, NeedsWalletRPC, TransactionsOut, WalletClientInfo
from chia.cmds.param_types import CliAddress, CliAmount
from chia.cmds.wallet import (
    AddProofRevealVCCMD,
    ApproveRCATsVCCMD,
    GetProofsForRootVCCMD,
    GetVcsCMD,
    MintVCCMD,
    RevokeVCCMD,
    UpdateProofsVCCMD,
)
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.blockchain_format.coin import coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.cr_cat_drivers import ProofsChecker, construct_cr_layer
from chia.wallet.vc_wallet.cr_cat_wallet import CRCATWallet
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord
from chia.wallet.vc_wallet.vc_wallet import VCWallet
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_request_types import (
    Addition,
    CATSpend,
    CreateSignedTransaction,
    GetTransactions,
    GetWallets,
    VCGet,
    VCMint,
    VCRevoke,
    WalletInfoResponse,
)
from chia.wallet.wallet_rpc_client import WalletRpcClient
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


async def mint_cr_cat(
    num_blocks: int,
    wallet_0: Wallet,
    wallet_node_0: WalletNode,
    client_0: WalletRpcClient,
    full_node_api: FullNodeSimulator,
    tx_config: TXConfig,
    authorized_providers: list[bytes32] = [],
    tail: Program = Program.NIL,
    proofs_checker: ProofsChecker = ProofsChecker(["foo", "bar"]),
) -> None:
    async with wallet_0.wallet_state_manager.new_action_scope(tx_config, push=True) as action_scope:
        our_puzzle = await action_scope.get_puzzle(wallet_0.wallet_state_manager)
    cat_puzzle: Program = construct_cat_puzzle(
        CAT_MOD,
        tail.get_tree_hash(),
        Program.to(1),
    )
    CAT_AMOUNT_0 = uint64(100)

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    tx = (
        await client_0.create_signed_transactions(
            CreateSignedTransaction(
                wallet_id=uint32(1),
                additions=[
                    Addition(
                        puzzle_hash=cat_puzzle.get_tree_hash(),
                        amount=CAT_AMOUNT_0,
                    )
                ],
            ),
            tx_config,
        )
    ).signed_tx
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    # Do the eve spend back to our wallet and add the CR layer
    cat_coin = next(c for c in spend_bundle.additions() if c.amount == CAT_AMOUNT_0)
    eve_spend = WalletSpendBundle(
        [
            make_spend(
                cat_coin,
                cat_puzzle,
                Program.to(
                    [
                        Program.to(
                            [
                                [
                                    51,
                                    construct_cr_layer(
                                        authorized_providers,
                                        proofs_checker.as_program(),
                                        our_puzzle,
                                    ).get_tree_hash(),
                                    CAT_AMOUNT_0,
                                    [our_puzzle.get_tree_hash()],
                                ],
                                [51, None, -113, tail, None],
                                [1, our_puzzle.get_tree_hash(), authorized_providers, proofs_checker.as_program()],
                            ]
                        ),
                        None,
                        cat_coin.name(),
                        coin_as_list(cat_coin),
                        [cat_coin.parent_coin_info, Program.to(1).get_tree_hash(), cat_coin.amount],
                        0,
                        0,
                    ]
                ),
            )
        ],
        G2Element(),
    )
    spend_bundle = WalletSpendBundle.aggregate([spend_bundle, eve_spend])
    await wallet_node_0.wallet_state_manager.add_pending_transactions(
        [dataclasses.replace(tx, spend_bundle=spend_bundle, name=spend_bundle.name())]
    )
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "config_overrides": {"automatically_add_unknown_cats": True},
            "blocks_needed": [2, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
async def test_vc_lifecycle(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    # Setup
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_node_0 = wallet_environments.environments[0].node
    wallet_node_1 = wallet_environments.environments[1].node
    wallet_0 = wallet_environments.environments[0].xch_wallet
    wallet_1 = wallet_environments.environments[1].xch_wallet
    client_0 = wallet_environments.environments[0].rpc_client
    client_1 = wallet_environments.environments[1].rpc_client
    client_info_0 = WalletClientInfo(
        env_0.rpc_client,
        env_0.wallet_state_manager.root_pubkey.get_fingerprint(),
        env_0.wallet_state_manager.config,
    )
    client_info_1 = WalletClientInfo(
        env_1.rpc_client,
        env_1.wallet_state_manager.root_pubkey.get_fingerprint(),
        env_1.wallet_state_manager.config,
    )
    tx_config_loader = NeedsTXConfig(
        min_coin_amount=CliAmount(amount=wallet_environments.tx_config.min_coin_amount, mojos=True),
        max_coin_amount=CliAmount(amount=wallet_environments.tx_config.max_coin_amount, mojos=True),
        coins_to_exclude=wallet_environments.tx_config.excluded_coin_ids,
        coins_to_include=wallet_environments.tx_config.included_coin_ids,
        amounts_to_exclude=[
            CliAmount(amount=amount, mojos=True) for amount in wallet_environments.tx_config.excluded_coin_amounts
        ],
        primary_coin=wallet_environments.tx_config.primary_coin,
        reuse=wallet_environments.tx_config.reuse_puzhash,
    )

    # Define wallet aliases
    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "vc": 3,
        "crcat": 4,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "crcat": 2,
        "vc": 3,
    }

    # Generate DID as an "authorized provider"
    async with wallet_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_id: bytes32 = bytes32.from_hexstr(
            (
                await DIDWallet.create_new_did_wallet(
                    wallet_node_0.wallet_state_manager, wallet_0, uint64(1), action_scope
                )
            ).get_my_DID()
        )
    await full_node_api.wait_for_wallet_synced(wallet_node_0)

    # Mint a VC
    async with wallet_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph = await action_scope.get_puzzle_hash(wallet_0.wallet_state_manager)
    await MintVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        did=CliAddress(did_id, encode_puzzle_hash(did_id, "did"), AddressType.DID),
        target_address=CliAddress(ph, encode_puzzle_hash(ph, "txch"), AddressType.XCH),
        fee=uint64(1_750_000_000_000),
        push=True,
    ).run()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        # 1_750_000_000_000 for VC mint fee, 1 for VC singleton, 1 for DID mint
                        "unconfirmed_wallet_balance": -1_750_000_000_002,
                        # I'm not sure incrementing pending_coin_removal_count here by 3 is the spirit of this number
                        # One existing coin has been removed and two ephemeral coins have been removed
                        # Does pending_coin_removal_count attempt to show the number of current pending removals
                        # Or does it intend to just mean all pending removals that we should eventually get states for?
                        "pending_coin_removal_count": 3,
                        "<=#spendable_balance": -1_750_000_000_002,
                        "<=#max_send_amount": -1_750_000_000_002,
                        "set_remainder": True,
                    },
                    "did": {"init": True, "set_remainder": True},
                    "vc": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "pending_change": 0,
                        "max_send_amount": 0,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        # 1_750_000_000_000 for VC mint fee, 1 for VC singleton, 1 for DID mint
                        "confirmed_wallet_balance": -1_750_000_000_002,
                        "pending_coin_removal_count": -3,  # 3 for VC mint, 1 for DID mint
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "vc": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )
    vc_wallet = env_0.wallet_state_manager.wallets[env_0.dealias_wallet_id("vc")]
    assert isinstance(vc_wallet, VCWallet)
    vc_record = (await vc_wallet.store.get_vc_record_list())[0]
    assert vc_record is not None

    # Spend VC
    proofs: VCProofs = VCProofs({"foo": "1", "bar": "1", "baz": "1", "qux": "1", "grault": "1"})
    proof_root: bytes32 = proofs.root()
    await UpdateProofsVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        vc_id=vc_record.vc.launcher_id,
        new_puzhash=None,
        new_proof_hash=proof_root.hex(),
        fee=uint64(100),
        push=True,
    ).run()
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -100,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -100,
                        "<=#max_send_amount": -100,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -100,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )
    vc_record_updated = await vc_wallet.store.get_vc_record(vc_record.vc.launcher_id)
    assert vc_record_updated is not None
    assert vc_record_updated.vc.proof_hash == proof_root

    # Do a mundane spend
    await UpdateProofsVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        vc_id=vc_record.vc.launcher_id,
        new_puzhash=None,
        new_proof_hash=None,
        fee=uint64(0),
        push=True,
    ).run()
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    # Add proofs to DB
    proof_flags = tuple(proofs.key_value_pairs.keys())
    await AddProofRevealVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        proof=proof_flags,
        root_only=False,
    ).run()
    # Doing it again just to make sure it doesn't care
    await AddProofRevealVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        proof=proof_flags,
        root_only=False,
    ).run()
    # Test a potential error
    capsys.readouterr()
    await AddProofRevealVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        proof=tuple(),
        root_only=False,
    ).run()
    assert "Must specify at least one proof" in capsys.readouterr().out
    # Test only the root calculation
    await AddProofRevealVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        proof=proof_flags,
        root_only=True,
    ).run()
    assert proof_root.hex() in capsys.readouterr().out
    # Test get_proofs_for_root
    await GetProofsForRootVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        proof_hash=proof_root.hex(),
    ).run()
    proof_output = capsys.readouterr().out
    for key in proofs.key_value_pairs:
        assert key in proof_output
    vc_wallet_0 = await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()
    stored_proofs = await vc_wallet_0.store.get_proofs_for_root(proof_root)
    assert stored_proofs is not None
    assert stored_proofs.key_value_pairs == proofs.key_value_pairs
    vc_records = await vc_wallet_0.store.get_vc_record_list(uint32(0), uint32(50))
    assert len(vc_records) == 1
    assert (await vc_wallet_0.store.get_proofs_for_root(proof_root)) is not None

    # Mint CR-CAT
    await mint_cr_cat(1, wallet_0, wallet_node_0, client_0, full_node_api, wallet_environments.tx_config, [did_id])
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -100,
                        "<=#spendable_balance": -100,
                        "<=#max_send_amount": -100,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -100,
                        "set_remainder": True,
                    },
                    "crcat": {
                        "init": True,
                        "confirmed_wallet_balance": 100,
                        "unconfirmed_wallet_balance": 100,
                        "spendable_balance": 100,
                        "pending_change": 0,
                        "max_send_amount": 100,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    cr_cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[env_0.dealias_wallet_id("crcat")]
    assert isinstance(cr_cat_wallet_0, CRCATWallet)
    assert await CRCATWallet.create(  # just testing the create method doesn't throw
        wallet_node_0.wallet_state_manager,
        wallet_node_0.wallet_state_manager.main_wallet,
        (await wallet_node_0.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.CRCAT))[0],
    )
    assert (
        WalletInfoResponse(
            data=bytes(cr_cat_wallet_0.info).hex(),
            id=env_0.dealias_wallet_id("crcat"),
            name=cr_cat_wallet_0.get_name(),
            type=uint8(cr_cat_wallet_0.type()),
            authorized_providers=cr_cat_wallet_0.info.authorized_providers,
            flags_needed=cr_cat_wallet_0.info.proofs_checker.flags,
        )
        == (await client_0.get_wallets(GetWallets(type=uint16(cr_cat_wallet_0.type())))).wallets[0]
    )
    assert await wallet_node_0.wallet_state_manager.get_wallet_for_asset_id(cr_cat_wallet_0.get_asset_id()) is not None
    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_1_ph = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)
    wallet_1_addr = encode_puzzle_hash(wallet_1_ph, "txch")
    txs = (
        await client_0.cat_spend(
            CATSpend(
                wallet_id=cr_cat_wallet_0.id(),
                amount=uint64(90),
                inner_address=wallet_1_addr,
                fee=uint64(2000000000),
                memos=["hey"],
                push=True,
            ),
            wallet_environments.tx_config,
        )
    ).transactions
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -2000000000,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -2000000000,
                        "<=#max_send_amount": -2000000000,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                    "crcat": {
                        "unconfirmed_wallet_balance": -90,
                        "spendable_balance": -100,
                        "max_send_amount": -100,
                        "pending_change": 10,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -2000000000,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                    "crcat": {
                        "confirmed_wallet_balance": -90,
                        "spendable_balance": 10,
                        "max_send_amount": 10,
                        "pending_change": -10,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "crcat": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "pending_change": 0,
                        "max_send_amount": 0,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 0,
                    }
                },
                post_block_additional_balance_info={
                    "crcat": {
                        "pending_approval_balance": 90,
                    },
                },
            ),
        ]
    )
    assert await wallet_node_1.wallet_state_manager.wallets[env_1.dealias_wallet_id("crcat")].match_hinted_coin(
        next(c for tx in txs for c in tx.additions if c.amount == 90), wallet_1_ph
    )
    pending_tx = (
        await client_1.get_transactions(
            GetTransactions(
                wallet_id=uint32(env_1.dealias_wallet_id("crcat")),
                start=uint32(0),
                end=uint32(1),
                reverse=True,
                type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CRCAT_PENDING]),
            )
        )
    ).transactions
    assert len(pending_tx) == 1

    # Send the VC to wallet_1 to use for the CR-CATs
    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)
    await UpdateProofsVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        vc_id=vc_record.vc.launcher_id,
        new_puzhash=ph,
        new_proof_hash=None,
        fee=uint64(0),
        push=True,
    ).run()
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    }
                },
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "vc": {"init": True, "set_remainder": True},
                }
            ),
        ]
    )
    await AddProofRevealVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_1),
        proof=proof_flags,
        root_only=False,
    ).run()

    # Claim the pending approval to our wallet
    await ApproveRCATsVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_1),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        wallet_id=env_1.dealias_wallet_id("crcat"),
        min_amount_to_claim=CliAmount(amount=uint64(90), mojos=True),
        fee=uint64(90),
        push=True,
    ).run()
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -90,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -90,
                        "<=#max_send_amount": -90,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                    "crcat": {
                        "unconfirmed_wallet_balance": 90,
                        "pending_change": 90,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -90,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                    "crcat": {
                        "confirmed_wallet_balance": 90,
                        "spendable_balance": 90,
                        "max_send_amount": 90,
                        "pending_change": -90,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": -1,
                    },
                },
                post_block_additional_balance_info={
                    "crcat": {
                        "pending_approval_balance": 0,
                    },
                },
            ),
        ]
    )

    # (Negative test) Try to spend a CR-CAT that we don't have a valid VC for
    with pytest.raises(ValueError):
        await client_0.cat_spend(
            CATSpend(
                wallet_id=cr_cat_wallet_0.id(),
                amount=uint64(10),
                inner_address=wallet_1_addr,
            ),
            tx_config=wallet_environments.tx_config,
        )

    # Test melting a CRCAT
    # This is intended to trigger an edge case where the output and change are the same forcing a new puzhash
    with wallet_environments.new_puzzle_hashes_allowed():
        tx = (
            await client_1.cat_spend(
                CATSpend(
                    wallet_id=env_1.dealias_wallet_id("crcat"),
                    amount=uint64(20),
                    inner_address=wallet_1_addr,
                    fee=uint64(0),
                    extra_delta=str(-50),
                    tail_reveal=b"\x80",
                    tail_solution=b"\x80",
                    push=True,
                ),
                tx_config=wallet_environments.tx_config,
            )
        ).transaction
    [tx] = await wallet_node_1.wallet_state_manager.add_pending_transactions([tx])
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": 20,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": 20,
                        "<=#max_send_amount": 20,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                    "crcat": {
                        "unconfirmed_wallet_balance": -50,
                        "spendable_balance": -90,
                        "max_send_amount": -90,
                        "pending_change": 40,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 20,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                    "crcat": {
                        "confirmed_wallet_balance": -50,  # should go straight to confirmed because we sent to ourselves
                        "spendable_balance": 40,
                        "max_send_amount": 40,
                        "pending_change": -40,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )
    vc_wallet_1 = env_1.wallet_state_manager.wallets[env_1.dealias_wallet_id("vc")]
    assert isinstance(vc_wallet_1, VCWallet)
    vc_record_updated = await vc_wallet_1.store.get_vc_record(vc_record.vc.launcher_id)
    assert vc_record_updated is not None

    # Revoke VC
    # Test with netiher
    await RevokeVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_1),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        parent_coin_id=None,
        vc_id=None,
        fee=uint64(1),
        push=False,
    ).run()
    assert "Must specify either --parent-coin-id or --vc-id" in capsys.readouterr().out
    # Try one that doesn't exist
    await RevokeVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_1),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        parent_coin_id=None,
        vc_id=bytes32.zeros,
        fee=uint64(1),
        push=False,
    ).run()
    assert f"Cannot find a VC with ID {bytes32.zeros.hex()}" in capsys.readouterr().out
    # Test with the VC ID
    await RevokeVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_1),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        parent_coin_id=None,
        vc_id=vc_record_updated.vc.launcher_id,
        fee=uint64(1),
        push=False,
    ).run()
    assert "Relevant TX records" in capsys.readouterr().out
    # Test with the parent coin ID
    await RevokeVCCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_0),
        tx_config_loader=tx_config_loader,
        transaction_writer=TransactionsOut(transaction_file_out=None),
        parent_coin_id=vc_record_updated.vc.coin.parent_coin_info,
        vc_id=None,
        fee=uint64(1),
        push=True,
    ).run()
    assert "Relevant TX records" in capsys.readouterr().out

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                },
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "vc": {
                        "unspent_coin_count": -1,
                    },
                },
            ),
        ]
    )
    assert (
        len(await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).store.get_unconfirmed_vcs()) == 0
    )


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
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
async def test_self_revoke(wallet_environments: WalletTestFramework) -> None:
    # Setup
    env_0: WalletEnvironment = wallet_environments.environments[0]
    wallet_node_0 = env_0.node
    wallet_0 = env_0.xch_wallet
    client_0 = env_0.rpc_client

    # Aliases
    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "vc": 3,
    }

    # Generate DID as an "authorized provider"
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(1), action_scope
        )
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node_0)
    did_id: bytes32 = bytes32.from_hexstr(did_wallet.get_my_DID())

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        ph = await action_scope.get_puzzle_hash(wallet_0.wallet_state_manager)
    # When reuse_puzhash=False, get_puzzle_hash derives a new key and commit() enqueues
    # puzzle-hash subscriptions on the new_peak_queue.  Wait for the queue to drain so
    # the wallet reports SYNCED before the RPC call that follows.
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node_0)
    vc_record = (
        await client_0.vc_mint(
            VCMint(
                did_id=encode_puzzle_hash(did_id, "did"),
                target_address=encode_puzzle_hash(ph, "txch"),
                fee=uint64(200),
                push=True,
            ),
            wallet_environments.tx_config,
        )
    ).vc_record
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # Balance checking for this spend covered in test_vc_lifecycle
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                    "vc": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "vc": {"set_remainder": True},
                },
            )
        ]
    )
    new_vc_record: VCRecord | None = (await client_0.vc_get(VCGet(vc_id=vc_record.vc.launcher_id))).vc_record
    assert new_vc_record is not None

    # Test a negative case real quick (mostly unrelated)
    with pytest.raises(ValueError, match="at the same time"):
        async with wallet_node_0.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=False
        ) as action_scope:
            await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).generate_signed_transaction(
                [uint64(1)],
                [await action_scope.get_puzzle_hash(wallet_node_0.wallet_state_manager)],
                action_scope,
                vc_id=new_vc_record.vc.launcher_id,
                new_proof_hash=bytes32.zeros,
                self_revoke=True,
            )

    # Send the DID to oblivion
    async with did_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await did_wallet.transfer_did(bytes32.zeros, uint64(0), action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={},
            )
        ]
    )

    # Make sure revoking still works
    await client_0.vc_revoke(
        VCRevoke(vc_parent_id=new_vc_record.vc.coin.parent_coin_info, push=True), wallet_environments.tx_config
    )
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # Balance checking for this spend covered in test_vc_lifecycle
                pre_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            )
        ]
    )
    vc_record_revoked: VCRecord | None = (await client_0.vc_get(VCGet(vc_id=vc_record.vc.launcher_id))).vc_record
    assert vc_record_revoked is None
    assert (
        len(await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).store.get_unconfirmed_vcs()) == 0
    )


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
async def test_cat_wallet_conversion(
    self_hostname: str,
    one_wallet_and_one_simulator_services: Any,
    trusted: Any,
) -> None:
    num_blocks = 1
    full_nodes, wallets, bt = one_wallet_and_one_simulator_services
    full_node_api: FullNodeSimulator = full_nodes[0]._api
    full_node_server = full_node_api.full_node.server
    wallet_service_0 = wallets[0]
    wallet_node_0 = wallet_service_0._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

    client_0 = await WalletRpcClient.create(
        bt.config["self_hostname"],
        wallet_service_0.rpc_server.listen_port,
        wallet_service_0.root_path,
        wallet_service_0.config,
    )

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}

    await wallet_node_0.server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    # Key point of test: create a normal CAT wallet first, and see if it gets converted to CR-CAT wallet
    await CATWallet.get_or_create_wallet_for_cat(
        wallet_node_0.wallet_state_manager, wallet_0, Program.NIL.get_tree_hash()
    )

    did_id = bytes32.zeros
    await mint_cr_cat(num_blocks, wallet_0, wallet_node_0, client_0, full_node_api, DEFAULT_TX_CONFIG, [did_id])
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    async def check_length(length: int, func: Callable[..., Awaitable[Any]], *args: Any) -> Literal[True] | None:
        if len(await func(*args)) == length:
            return True
        return None  # pragma: no cover

    await time_out_assert_not_none(
        15, check_length, 1, wallet_node_0.wallet_state_manager.get_all_wallet_info_entries, WalletType.CRCAT
    )
    await time_out_assert_not_none(
        15, check_length, 0, wallet_node_0.wallet_state_manager.get_all_wallet_info_entries, WalletType.CAT
    )

    client_0.close()
    await client_0.await_closed()


def test_vc_command_parsing() -> None:
    bare_rpc = NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None)
    did_puzzle_hash = bytes32([1] * 32)
    did_address = encode_puzzle_hash(did_puzzle_hash, "did:chia:")
    target_puzzle_hash = bytes32([2] * 32)
    target_address = encode_puzzle_hash(target_puzzle_hash, "txch")
    vc_id = bytes32([3] * 32)
    parent_coin_id = bytes32([4] * 32)
    new_puzhash = bytes32([5] * 32)
    new_proof_hash = bytes32([6] * 32)
    proof_root = bytes32([7] * 32)

    check_click_parsing(
        MintVCCMD(
            rpc_info=bare_rpc,
            tx_config_loader=NeedsTXConfig(
                coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple()
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            did=CliAddress(did_puzzle_hash, did_address, AddressType.DID),
            target_address=CliAddress(target_puzzle_hash, target_address, AddressType.XCH),
            fee=uint64(500000000000),
        ),
        "-d",
        did_address,
        "-t",
        target_address,
        "-m",
        "0.5",
        context=ChiaCliContext(expected_prefix="txch"),
    )

    check_click_parsing(
        GetVcsCMD(
            rpc_info=bare_rpc,
            start=0,
            count=50,
        ),
    )

    check_click_parsing(
        GetVcsCMD(
            rpc_info=bare_rpc,
            start=10,
            count=10,
        ),
        "-s",
        "10",
        "-c",
        "10",
    )

    check_click_parsing(
        UpdateProofsVCCMD(
            rpc_info=bare_rpc,
            tx_config_loader=NeedsTXConfig(
                coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple()
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            vc_id=vc_id,
            new_puzhash=new_puzhash,
            new_proof_hash=new_proof_hash.hex(),
            fee=uint64(500000000000),
        ),
        "--vc-id",
        vc_id.hex(),
        "-t",
        new_puzhash.hex(),
        "-p",
        new_proof_hash.hex(),
        "-m",
        "0.5",
    )

    check_click_parsing(
        UpdateProofsVCCMD(
            rpc_info=bare_rpc,
            tx_config_loader=NeedsTXConfig(
                coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple()
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            vc_id=vc_id,
            new_puzhash=None,
            new_proof_hash=None,
            fee=uint64(500000000000),
        ),
        "--vc-id",
        vc_id.hex(),
        "-m",
        "0.5",
    )

    check_click_parsing(
        AddProofRevealVCCMD(
            rpc_info=bare_rpc,
            proof=tuple(),
            root_only=False,
        ),
    )

    check_click_parsing(
        AddProofRevealVCCMD(
            rpc_info=bare_rpc,
            proof=("test_proof", "test_proof2"),
            root_only=True,
        ),
        "-p",
        "test_proof",
        "-p",
        "test_proof2",
        "-r",
    )

    check_click_parsing(
        GetProofsForRootVCCMD(
            rpc_info=bare_rpc,
            proof_hash=proof_root.hex(),
        ),
        "-r",
        proof_root.hex(),
    )

    check_click_parsing(
        RevokeVCCMD(
            rpc_info=bare_rpc,
            tx_config_loader=NeedsTXConfig(
                coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple()
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            parent_coin_id=parent_coin_id,
            vc_id=None,
            fee=uint64(500000000000),
        ),
        "-p",
        parent_coin_id.hex(),
        "-m",
        "0.5",
    )

    check_click_parsing(
        RevokeVCCMD(
            rpc_info=bare_rpc,
            tx_config_loader=NeedsTXConfig(
                coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple()
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            parent_coin_id=None,
            vc_id=vc_id,
            fee=uint64(500000000000),
        ),
        "--vc-id",
        vc_id.hex(),
        "-m",
        "0.5",
    )

    check_click_parsing(
        ApproveRCATsVCCMD(
            rpc_info=bare_rpc,
            tx_config_loader=NeedsTXConfig(
                coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple()
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            wallet_id=2,
            min_amount_to_claim=CliAmount(amount=Decimal("0.001"), mojos=False),
            fee=uint64(500000000000),
        ),
        "-i",
        "2",
        "-a",
        "1",
        "-m",
        "0.5",
        "--min-amount-to-claim",
        "0.001",
    )
