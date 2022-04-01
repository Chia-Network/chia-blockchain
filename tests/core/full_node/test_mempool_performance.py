# flake8: noqa: F811, F401
from dataclasses import dataclass, field
import logging
from statistics import mean, quantiles
from typing import Iterable, List, Tuple
import time

import pytest

from chia.protocols import full_node_protocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_node import WalletNode
from tests.connection_utils import connect_and_get_peer
from tests.time_out_assert import time_out_assert


def wallet_height_at_least(wallet_node, h):
    height = wallet_node.wallet_state_manager.blockchain.get_peak_height()
    if height == h:
        return True
    return False


async def wallet_balance_at_least(wallet_node: WalletNode, balance):
    assert wallet_node.wallet_state_manager is not None
    b = await wallet_node.wallet_state_manager.get_confirmed_balance_for_wallet(1)
    if b >= balance:
        return True
    return False


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Statistics:
    minimum: float
    maximum: float
    mean: float
    percentile_90: float
    data: Tuple[float]

    @classmethod
    def create(cls, data: Iterable[float]):
        tupled_data = tuple(data)

        return cls(
            minimum=min(tupled_data),
            maximum=max(tupled_data),
            mean=mean(tupled_data),
            percentile_90=quantiles(tupled_data)[-1],
            data=tupled_data,
        )


class TestMempoolPerformance:
    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_mempool_update_performance(self, bt, wallet_nodes_mempool_perf, default_400_blocks, self_hostname):
        blocks = default_400_blocks
        full_nodes, wallets = wallet_nodes_mempool_perf
        wallet_node = wallets[0][0]
        wallet_server = wallets[0][1]
        full_node_api_1 = full_nodes[0]
        full_node_api_2 = full_nodes[1]
        server_1 = full_node_api_1.full_node.server
        server_2 = full_node_api_2.full_node.server
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        for block in blocks:
            await full_node_api_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await time_out_assert(60, wallet_height_at_least, True, wallet_node, 399)
        send_amount = 40000000000000
        fee_amount = 2213
        await time_out_assert(60, wallet_balance_at_least, True, wallet_node, send_amount + fee_amount)

        big_transaction: TransactionRecord = await wallet.generate_signed_transaction(send_amount, ph, fee_amount)

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        await full_node_api_1.respond_transaction(
            full_node_protocol.RespondTransaction(big_transaction.spend_bundle), peer, test=True
        )
        cons = list(server_1.all_connections.values())[:]
        for con in cons:
            await con.close()

        blocks = bt.get_consecutive_blocks(3, blocks)
        await full_node_api_1.full_node.respond_block(full_node_protocol.RespondBlock(blocks[-3]))

        fast_durations: List[float] = []
        slow_durations: List[float] = []

        for idx, block in enumerate(blocks):
            start_t_2 = time.time()
            await full_node_api_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
            end_t_2 = time.time()
            duration = end_t_2 - start_t_2
            if idx >= len(blocks) - 3:
                slow_durations.append(duration)
            else:
                fast_durations.append(duration)

        fast_statistics = Statistics.create(data=fast_durations)
        slow_statistics = Statistics.create(data=slow_durations)

        message = f"fast: {fast_statistics}\n\nslow: {slow_statistics}"
        print(f"\n\n{message}")
        assert (
            fast_statistics.percentile_90 < 0.00005 and slow_statistics.percentile_90 < 0.1
        ), f"90th percentile not in range\n\n{message}"
