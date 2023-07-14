from __future__ import annotations

from typing import Any, Awaitable, Callable, List, Optional

import pytest
from blspy import G2Element
from typing_extensions import Literal

from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.coin import coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.cr_cat_drivers import ProofsChecker, construct_cr_layer
from chia.wallet.vc_wallet.cr_cat_wallet import CRCATWallet
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode


async def mint_cr_cat(
    num_blocks: int,
    wallet_0: Wallet,
    wallet_node_0: WalletNode,
    client_0: WalletRpcClient,
    full_node_api: FullNodeSimulator,
    authorized_providers: List[bytes32] = [],
    tail: Program = Program.to(None),
    proofs_checker: ProofsChecker = ProofsChecker(["foo", "bar"]),
) -> None:
    our_puzzle: Program = await wallet_0.get_new_puzzle()
    cat_puzzle: Program = construct_cat_puzzle(
        CAT_MOD,
        tail.get_tree_hash(),
        Program.to(1),
    )
    CAT_AMOUNT_0 = uint64(100)

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    tx = await client_0.create_signed_transaction(
        [
            {
                "puzzle_hash": cat_puzzle.get_tree_hash(),
                "amount": CAT_AMOUNT_0,
            }
        ],
        wallet_id=1,
    )
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    # Do the eve spend back to our wallet and add the CR layer
    cat_coin = next(c for c in spend_bundle.additions() if c.amount == CAT_AMOUNT_0)
    eve_spend = SpendBundle(
        [
            CoinSpend(
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
    spend_bundle = SpendBundle.aggregate([spend_bundle, eve_spend])
    await client_0.push_tx(spend_bundle)  # type: ignore [no-untyped-call]
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_vc_lifecycle(self_hostname: str, two_wallet_nodes_services: Any, trusted: Any) -> None:
    num_blocks = 1
    full_nodes, wallets, bt = two_wallet_nodes_services
    full_node_api: FullNodeSimulator = full_nodes[0]._api
    full_node_server = full_node_api.full_node.server
    wallet_service_0 = wallets[0]
    wallet_service_1 = wallets[1]
    wallet_node_0 = wallet_service_0._node
    wallet_node_1 = wallet_service_1._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    client_0 = await WalletRpcClient.create(
        bt.config["self_hostname"],
        wallet_service_0.rpc_server.listen_port,
        wallet_service_0.root_path,
        wallet_service_0.config,
    )
    client_1 = await WalletRpcClient.create(
        bt.config["self_hostname"],
        wallet_service_1.rpc_server.listen_port,
        wallet_service_1.root_path,
        wallet_service_1.config,
    )
    wallet_node_0.config["automatically_add_unknown_cats"] = True
    wallet_node_1.config["automatically_add_unknown_cats"] = True

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

    await wallet_node_0.server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_node_1.server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    confirmed_balance: int = await wallet_0.get_confirmed_balance()
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    confirmed_balance -= 1
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())

    spend_bundle = spend_bundle_list[0].spend_bundle
    assert spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await time_out_assert(15, wallet_0.get_confirmed_balance, confirmed_balance)
    did_id = bytes32.from_hexstr(did_wallet.get_my_DID())
    vc_record, txs = await client_0.vc_mint(did_id, target_address=await wallet_0.get_new_puzzlehash(), fee=uint64(200))
    confirmed_balance -= 1
    confirmed_balance -= 200
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await time_out_assert(15, wallet_0.get_confirmed_balance, confirmed_balance)
    vc_wallet = await wallet_node_0.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.VC)
    assert len(vc_wallet) == 1
    new_vc_record: Optional[VCRecord] = await client_0.vc_get(vc_record.vc.launcher_id)
    assert new_vc_record is not None

    # Spend VC
    proofs: VCProofs = VCProofs({"foo": "1", "bar": "1", "baz": "1", "qux": "1", "grault": "1"})
    proof_root: bytes32 = proofs.root()
    txs = await client_0.vc_spend(
        vc_record.vc.launcher_id,
        new_proof_hash=proof_root,
        fee=uint64(100),
    )
    confirmed_balance -= 100
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await time_out_assert(15, wallet_0.get_confirmed_balance, confirmed_balance)
    vc_record_updated: Optional[VCRecord] = await client_0.vc_get(vc_record.vc.launcher_id)
    assert vc_record_updated is not None
    assert vc_record_updated.vc.proof_hash == proof_root

    # Do a mundane spend
    txs = await client_0.vc_spend(vc_record.vc.launcher_id)
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await time_out_assert(15, wallet_0.get_confirmed_balance, confirmed_balance)

    async def check_vc_record_has_parent_id(
        parent_id: bytes32, client: WalletRpcClient, launcher_id: bytes32
    ) -> Optional[Literal[True]]:
        vc_record = await client.vc_get(launcher_id)
        result: Optional[Literal[True]] = None
        if vc_record is not None:
            result = True if vc_record.vc.coin.parent_coin_info == parent_id else None
        return result

    await time_out_assert_not_none(
        10, check_vc_record_has_parent_id, vc_record_updated.vc.coin.name(), client_0, vc_record.vc.launcher_id
    )
    vc_record_updated = await client_0.vc_get(vc_record.vc.launcher_id)
    assert vc_record_updated is not None

    # Add proofs to DB
    await client_0.vc_add_proofs(proofs.key_value_pairs)
    assert await client_0.vc_get_proofs_for_root(proof_root) == proofs.key_value_pairs
    vc_records, fetched_proofs = await client_0.vc_get_list()
    assert len(vc_records) == 1
    assert fetched_proofs[proof_root.hex()] == proofs.key_value_pairs

    await mint_cr_cat(num_blocks, wallet_0, wallet_node_0, client_0, full_node_api, [did_id])
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    confirmed_balance += 2_000_000_000_000 * num_blocks
    confirmed_balance -= 100  # cat mint amount

    # Send CR-CAT to another wallet
    async def check_length(length: int, func: Callable[..., Awaitable[Any]], *args: Any) -> Optional[Literal[True]]:
        if len(await func(*args)) == length:
            return True
        return None  # pragma: no cover

    await time_out_assert_not_none(
        15, check_length, 1, wallet_node_0.wallet_state_manager.get_all_wallet_info_entries, WalletType.CRCAT
    )
    cr_cat_wallet_id_0: uint16 = (
        await wallet_node_0.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.CRCAT)
    )[0].id
    cr_cat_wallet_0: CRCATWallet = wallet_node_0.wallet_state_manager.wallets[cr_cat_wallet_id_0]
    assert await wallet_node_0.wallet_state_manager.get_wallet_for_asset_id(cr_cat_wallet_0.get_asset_id()) is not None
    wallet_1_addr = encode_puzzle_hash(await wallet_1.get_new_puzzlehash(), "txch")
    tx = await client_0.cat_spend(
        cr_cat_wallet_0.id(),
        uint64(90),
        wallet_1_addr,
        uint64(2000000000),
        memos=["hey"],
    )
    confirmed_balance -= 2000000000
    await wallet_node_0.wallet_state_manager.add_pending_transaction(tx)
    assert tx.spend_bundle is not None
    spend_bundle = tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)
    await time_out_assert(15, wallet_0.get_confirmed_balance, confirmed_balance)
    await time_out_assert(15, cr_cat_wallet_0.get_confirmed_balance, 10)

    # Check the other wallet recieved it
    await time_out_assert_not_none(
        15, check_length, 1, wallet_node_1.wallet_state_manager.get_all_wallet_info_entries, WalletType.CRCAT
    )
    cr_cat_wallet_info = (
        await wallet_node_1.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.CRCAT)
    )[0]
    cr_cat_wallet_id_1: uint16 = cr_cat_wallet_info.id
    cr_cat_wallet_1: CRCATWallet = wallet_node_1.wallet_state_manager.wallets[cr_cat_wallet_id_1]
    assert await CRCATWallet.create(  # just testing the create method doesn't throw
        wallet_node_1.wallet_state_manager,
        wallet_node_1.wallet_state_manager.main_wallet,
        cr_cat_wallet_info,
    )
    await time_out_assert(15, cr_cat_wallet_1.get_confirmed_balance, 0)
    await time_out_assert(15, cr_cat_wallet_1.get_pending_approval_balance, 90)
    await time_out_assert(15, cr_cat_wallet_1.get_unconfirmed_balance, 90)
    assert await client_1.get_wallet_balance(cr_cat_wallet_id_1) == {
        "confirmed_wallet_balance": 0,
        "unconfirmed_wallet_balance": 0,
        "spendable_balance": 0,
        "pending_change": 0,
        "max_send_amount": 0,
        "unspent_coin_count": 0,
        "pending_coin_removal_count": 0,
        "pending_approval_balance": 90,
        "wallet_id": cr_cat_wallet_id_1,
        "wallet_type": cr_cat_wallet_1.type().value,
        "asset_id": cr_cat_wallet_1.get_asset_id(),
        "fingerprint": wallet_node_1.logged_in_fingerprint,
    }
    pending_tx = await client_1.get_transactions(
        cr_cat_wallet_1.id(),
        0,
        1,
        reverse=True,
        type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CRCAT_PENDING]),
    )
    assert len(pending_tx) == 1

    # Send the VC to wallet_1 to use for the CR-CATs
    txs = await client_0.vc_spend(vc_record.vc.launcher_id, new_puzhash=await wallet_1.get_new_puzzlehash())
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)
    vc_record_updated = await client_1.vc_get(vc_record.vc.launcher_id)
    assert vc_record_updated is not None
    await client_1.vc_add_proofs(proofs.key_value_pairs)

    # Claim the pending approval to our wallet
    txs = await client_1.crcat_approve_pending(
        uint32(cr_cat_wallet_id_1),
        uint64(90),
        fee=uint64(90),
    )
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)
    await time_out_assert(15, cr_cat_wallet_1.get_confirmed_balance, 90)
    await time_out_assert(15, cr_cat_wallet_1.get_pending_approval_balance, 0)
    await time_out_assert(15, cr_cat_wallet_1.get_unconfirmed_balance, 90)
    await time_out_assert(
        15, cr_cat_wallet_1.wallet_state_manager.get_confirmed_balance_for_wallet, 90, cr_cat_wallet_id_1
    )
    await time_out_assert_not_none(
        10, check_vc_record_has_parent_id, vc_record_updated.vc.coin.name(), client_1, vc_record.vc.launcher_id
    )
    vc_record_updated = await client_1.vc_get(vc_record.vc.launcher_id)
    assert vc_record_updated is not None

    # (Negative test) Try to spend a CR-CAT that we don't have a valid VC for
    with pytest.raises(ValueError):
        tx = await client_0.cat_spend(
            cr_cat_wallet_0.id(),
            uint64(10),
            wallet_1_addr,
        )

    # Test melting a CRCAT
    tx = await client_1.cat_spend(
        cr_cat_wallet_id_1,
        uint64(20),
        wallet_1_addr,
        uint64(0),
        cat_discrepancy=(-50, Program.to(None), Program.to(None)),
        reuse_puzhash=True,
    )
    await wallet_node_1.wallet_state_manager.add_pending_transaction(tx)
    assert tx.spend_bundle is not None
    spend_bundle = tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)
    # should go straight to confirmed because we sent to ourselves
    await time_out_assert(15, cr_cat_wallet_1.get_confirmed_balance, 40)
    await time_out_assert(15, cr_cat_wallet_1.get_pending_approval_balance, 0)
    await time_out_assert(15, cr_cat_wallet_1.get_unconfirmed_balance, 40)

    # Revoke VC
    await time_out_assert_not_none(
        10, check_vc_record_has_parent_id, vc_record_updated.vc.coin.name(), client_1, vc_record.vc.launcher_id
    )
    vc_record_updated = await client_1.vc_get(vc_record_updated.vc.launcher_id)
    assert vc_record_updated is not None
    txs = await client_0.vc_revoke(vc_record_updated.vc.coin.parent_coin_info, uint64(1))
    confirmed_balance -= 1
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await time_out_assert(15, wallet_0.get_confirmed_balance, confirmed_balance)
    vc_record_revoked: Optional[VCRecord] = await client_1.vc_get(vc_record.vc.launcher_id)
    assert vc_record_revoked is None
    assert (
        len(await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).store.get_unconfirmed_vcs()) == 0
    )


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
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

    await wallet_node_0.server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    # Key point of test: create a normal CAT wallet first, and see if it gets converted to CR-CAT wallet
    await CATWallet.get_or_create_wallet_for_cat(
        wallet_node_0.wallet_state_manager, wallet_0, Program.to(None).get_tree_hash().hex()
    )

    did_id = bytes32([0] * 32)
    await mint_cr_cat(num_blocks, wallet_0, wallet_node_0, client_0, full_node_api, [did_id])
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    async def check_length(length: int, func: Callable[..., Awaitable[Any]], *args: Any) -> Optional[Literal[True]]:
        if len(await func(*args)) == length:
            return True
        return None  # pragma: no cover

    await time_out_assert_not_none(
        15, check_length, 1, wallet_node_0.wallet_state_manager.get_all_wallet_info_entries, WalletType.CRCAT
    )
    await time_out_assert_not_none(
        15, check_length, 0, wallet_node_0.wallet_state_manager.get_all_wallet_info_entries, WalletType.CAT
    )
