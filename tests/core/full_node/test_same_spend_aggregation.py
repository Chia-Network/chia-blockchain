from typing import List, Optional, Set

import pytest

from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import AmountWithPuzzlehash
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_node import WalletNode
from tests.connection_utils import connect_and_get_peer
from tests.util.wallet_is_synced import wallet_is_synced


@pytest.mark.asyncio
async def test_same_spend_aggregation(setup_two_nodes_and_wallet, self_hostname):
    nodes, wallets, bt = setup_two_nodes_and_wallet
    server_1 = nodes[0].full_node.server
    server_2 = nodes[1].full_node.server
    wallet_server = wallets[0][1]
    full_node_1: FullNodeSimulator = nodes[0]
    full_node_2: FullNodeSimulator = nodes[1]
    wallet_node_1: WalletNode = wallets[0][0]
    wallet: Wallet = wallet_node_1.wallet_state_manager.main_wallet

    await wallet_server.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    peer = await connect_and_get_peer(server_1, server_2, self_hostname)

    ph = await wallet.get_new_puzzlehash()
    phs = [await wallet.get_new_puzzlehash() for _ in range(3)]

    for i in range(2):
        await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(20, wallet_is_synced, True, wallet_node_1, full_node_1)

    # Create a tx spending coins A and B
    # Create a tx spending coins B and C
    other_recipients: List[AmountWithPuzzlehash] = [
        AmountWithPuzzlehash(amount=uint64(200), puzzlehash=p, memos=[]) for p in phs[1:]
    ]
    tx: TransactionRecord = await wallet.generate_signed_transaction(uint64(200), phs[0], primaries=other_recipients)
    res: Optional[Message] = await full_node_1.send_transaction(wallet_protocol.SendTransaction(tx.spend_bundle))
    assert res is not None and ProtocolMessageTypes(res.type) == ProtocolMessageTypes.transaction_ack
    res_parsed: wallet_protocol.TransactionAck = wallet_protocol.TransactionAck.from_bytes(res.data)
    assert res_parsed.status == MempoolInclusionStatus.SUCCESS

    await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(20, wallet_is_synced, True, wallet_node_1, full_node_1)

    coins: List[WalletCoinRecord] = list(
        await wallet_node_1.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(1)
    )
    assert len(coins) == 7  # Two blocks farmed plus 3 txs

    tx_a: TransactionRecord = await wallet.generate_signed_transaction(uint64(30), ph, coins={coins[0].coin})
    tx_b: TransactionRecord = await wallet.generate_signed_transaction(uint64(30), ph, coins={coins[1].coin})
    tx_c: TransactionRecord = await wallet.generate_signed_transaction(uint64(30), ph, coins={coins[2].coin})

    ab_bundle: SpendBundle = SpendBundle.aggregate([tx_a.spend_bundle, tx_b.spend_bundle])
    bc_bundle: SpendBundle = SpendBundle.aggregate([tx_c.spend_bundle, tx_b.spend_bundle])

    # submit both transactions
    for bundle in [ab_bundle, bc_bundle]:
        res = await full_node_1.send_transaction(wallet_protocol.SendTransaction(bundle))
        assert res is not None and ProtocolMessageTypes(res.type) == ProtocolMessageTypes.transaction_ack
        res_parsed = wallet_protocol.TransactionAck.from_bytes(res.data)
        assert res_parsed.status == MempoolInclusionStatus.SUCCESS
