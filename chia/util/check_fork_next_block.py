from __future__ import annotations

from typing import Callable, List

from chia.consensus.blockchain_interface import BlockchainInterface
from chia.util.ints import uint32


async def check_fork_next_block(
    blockchain: BlockchainInterface, fork_point_height: uint32, peers_with_peak: List, check_block_future: Callable
):
    our_peak_height = blockchain.get_peak_height()
    ses_heigths = blockchain.get_ses_heights()
    if len(ses_heigths) > 2 and our_peak_height is not None:
        ses_heigths.sort()
        max_fork_ses_height = ses_heigths[-3]
        potential_peek = uint32(our_peak_height + 1)
        # This is the fork point in SES in the case where no fork was detected
        if blockchain.get_peak_height() is not None and fork_point_height == max_fork_ses_height:
            for peer in peers_with_peak.copy():
                if peer.closed:
                    peers_with_peak.remove(peer)
                    continue
                # Grab a block at peak + 1 and check if fork point is actually our current height
                if await check_block_future(peer, potential_peek, blockchain):
                    fork_point_height = our_peak_height
                    break
    return fork_point_height
