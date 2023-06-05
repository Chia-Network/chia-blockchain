from __future__ import annotations

from typing import Any, Optional

import pytest
from typing_extensions import Literal

from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord


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
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet  # just to farm to for processing TXs

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
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await wallet_node_0.server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_node_1.server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
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

    assert did_wallet.did_info.current_inner is not None
    # Spend VC
    proofs: VCProofs = VCProofs({"foo": "bar", "baz": "qux", "corge": "grault"})
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

    # Revoke VC
    txs = await client_0.vc_revoke(vc_record_updated.vc.coin.parent_coin_info, uint64(1))
    confirmed_balance -= 1
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await time_out_assert(15, wallet_0.get_confirmed_balance, confirmed_balance)
    vc_record_revoked: Optional[VCRecord] = await client_0.vc_get(vc_record.vc.launcher_id)
    assert vc_record_revoked is None
    assert (
        len(await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).store.get_unconfirmed_vcs()) == 0
    )
