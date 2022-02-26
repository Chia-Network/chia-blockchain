import asyncio
import logging
import random
from typing import List, Optional, Tuple, Union, Dict

from chia.consensus.constants import ConsensusConstants
from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import (
    RequestAdditions,
    RespondAdditions,
    RejectAdditionsRequest,
    RejectRemovalsRequest,
    RespondRemovals,
    RequestRemovals,
    RespondBlockHeader,
    CoinState,
    RespondToPhUpdates,
    RespondToCoinUpdates,
    RespondHeaderBlocks,
    RequestHeaderBlocks,
)
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import hash_coin_list, Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32
from chia.util.merkle_set import confirm_not_included_already_hashed, confirm_included_already_hashed, MerkleSet
from chia.wallet.util.peer_request_cache import PeerRequestCache

log = logging.getLogger(__name__)


async def fetch_last_tx_from_peer(height: uint32, peer: WSChiaConnection) -> Optional[HeaderBlock]:
    request_height: int = height
    while True:
        if request_height == -1:
            return None
        request = wallet_protocol.RequestBlockHeader(uint32(request_height))
        response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
        if response is not None and isinstance(response, RespondBlockHeader):
            if response.header_block.is_transaction_block:
                return response.header_block
        else:
            break
        request_height = request_height - 1
    return None


async def subscribe_to_phs(
    puzzle_hashes: List[bytes32],
    peer: WSChiaConnection,
    min_height: int,
) -> List[CoinState]:
    """
    Tells full nodes that we are interested in puzzle hashes, and returns the response.
    """
    msg = wallet_protocol.RegisterForPhUpdates(puzzle_hashes, uint32(max(min_height, uint32(0))))
    all_coins_state: Optional[RespondToPhUpdates] = await peer.register_interest_in_puzzle_hash(msg)
    if all_coins_state is not None:
        return all_coins_state.coin_states
    return []


async def subscribe_to_coin_updates(
    coin_names: List[bytes32],
    peer: WSChiaConnection,
    min_height: int,
) -> List[CoinState]:
    """
    Tells full nodes that we are interested in coin ids, and returns the response.
    """
    msg = wallet_protocol.RegisterForCoinUpdates(coin_names, uint32(max(0, min_height)))
    all_coins_state: Optional[RespondToCoinUpdates] = await peer.register_interest_in_coin(msg)
    if all_coins_state is not None:
        return all_coins_state.coin_states
    return []


def validate_additions(
    coins: List[Tuple[bytes32, List[Coin]]],
    proofs: Optional[List[Tuple[bytes32, bytes, Optional[bytes]]]],
    root: bytes32,
):
    if proofs is None:
        # Verify root
        additions_merkle_set = MerkleSet()

        # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
        for puzzle_hash, coins_l in coins:
            additions_merkle_set.add_already_hashed(puzzle_hash)
            additions_merkle_set.add_already_hashed(hash_coin_list(coins_l))

        additions_root = additions_merkle_set.get_root()
        if root != additions_root:
            return False
    else:
        for i in range(len(coins)):
            assert coins[i][0] == proofs[i][0]
            coin_list_1: List[Coin] = coins[i][1]
            puzzle_hash_proof: Optional[bytes] = proofs[i][1]
            coin_list_proof: Optional[bytes] = proofs[i][2]
            if len(coin_list_1) == 0:
                # Verify exclusion proof for puzzle hash
                assert puzzle_hash_proof is not None
                not_included = confirm_not_included_already_hashed(
                    root,
                    coins[i][0],
                    puzzle_hash_proof,
                )
                if not_included is False:
                    return False
            else:
                try:
                    # Verify inclusion proof for coin list
                    assert coin_list_proof is not None
                    included = confirm_included_already_hashed(
                        root,
                        hash_coin_list(coin_list_1),
                        coin_list_proof,
                    )
                    if included is False:
                        return False
                except AssertionError:
                    return False
                try:
                    # Verify inclusion proof for puzzle hash
                    assert puzzle_hash_proof is not None
                    included = confirm_included_already_hashed(
                        root,
                        coins[i][0],
                        puzzle_hash_proof,
                    )
                    if included is False:
                        return False
                except AssertionError:
                    return False

    return True


def validate_removals(
    coins: List[Tuple[bytes32, Optional[Coin]]], proofs: Optional[List[Tuple[bytes32, bytes]]], root: bytes32
):
    if proofs is None:
        # If there are no proofs, it means all removals were returned in the response.
        # we must find the ones relevant to our wallets.

        # Verify removals root
        removals_merkle_set = MerkleSet()
        for name_coin in coins:
            name, coin = name_coin
            if coin is not None:
                removals_merkle_set.add_already_hashed(coin.name())
        removals_root = removals_merkle_set.get_root()
        if root != removals_root:
            return False
    else:
        # This means the full node has responded only with the relevant removals
        # for our wallet. Each merkle proof must be verified.
        if len(coins) != len(proofs):
            return False
        for i in range(len(coins)):
            # Coins are in the same order as proofs
            if coins[i][0] != proofs[i][0]:
                return False
            coin = coins[i][1]
            if coin is None:
                # Verifies merkle proof of exclusion
                not_included = confirm_not_included_already_hashed(
                    root,
                    coins[i][0],
                    proofs[i][1],
                )
                if not_included is False:
                    return False
            else:
                # Verifies merkle proof of inclusion of coin name
                if coins[i][0] != coin.name():
                    return False
                included = confirm_included_already_hashed(
                    root,
                    coin.name(),
                    proofs[i][1],
                )
                if included is False:
                    return False
    return True


async def request_and_validate_removals(
    peer: WSChiaConnection, height: uint32, header_hash: bytes32, coin_name: bytes32, removals_root: bytes32
) -> bool:
    removals_request = RequestRemovals(height, header_hash, [coin_name])

    removals_res: Optional[Union[RespondRemovals, RejectRemovalsRequest]] = await peer.request_removals(
        removals_request
    )
    if removals_res is None or isinstance(removals_res, RejectRemovalsRequest):
        return False
    assert removals_res.proofs is not None
    return validate_removals(removals_res.coins, removals_res.proofs, removals_root)


async def request_and_validate_additions(
    peer: WSChiaConnection, height: uint32, header_hash: bytes32, puzzle_hash: bytes32, additions_root: bytes32
):
    additions_request = RequestAdditions(height, header_hash, [puzzle_hash])
    additions_res: Optional[Union[RespondAdditions, RejectAdditionsRequest]] = await peer.request_additions(
        additions_request
    )
    if additions_res is None or isinstance(additions_res, RejectAdditionsRequest):
        return False

    return validate_additions(
        additions_res.coins,
        additions_res.proofs,
        additions_root,
    )


def get_block_challenge(
    constants: ConsensusConstants,
    header_block: FullBlock,
    all_blocks: Dict[bytes32, FullBlock],
    genesis_block: bool,
    overflow: bool,
    skip_overflow_last_ss_validation: bool,
) -> Optional[bytes32]:
    if len(header_block.finished_sub_slots) > 0:
        if overflow:
            # New sub-slot with overflow block
            if skip_overflow_last_ss_validation:
                # In this case, we are missing the final sub-slot bundle (it's not finished yet), however
                # There is a whole empty slot before this block is infused
                challenge: bytes32 = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
            else:
                challenge = header_block.finished_sub_slots[
                    -1
                ].challenge_chain.challenge_chain_end_of_slot_vdf.challenge
        else:
            # No overflow, new slot with a new challenge
            challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
    else:
        if genesis_block:
            challenge = constants.GENESIS_CHALLENGE
        else:
            if overflow:
                if skip_overflow_last_ss_validation:
                    # Overflow infusion without the new slot, so get the last challenge
                    challenges_to_look_for = 1
                else:
                    # Overflow infusion, so get the second to last challenge. skip_overflow_last_ss_validation is False,
                    # Which means no sub slots are omitted
                    challenges_to_look_for = 2
            else:
                challenges_to_look_for = 1
            reversed_challenge_hashes: List[bytes32] = []
            if header_block.height == 0:
                return constants.GENESIS_CHALLENGE
            if header_block.prev_header_hash not in all_blocks:
                return None
            curr: Optional[FullBlock] = all_blocks[header_block.prev_header_hash]
            while len(reversed_challenge_hashes) < challenges_to_look_for:
                if curr is None:
                    return None
                if len(curr.finished_sub_slots) > 0:
                    reversed_challenge_hashes += reversed(
                        [slot.challenge_chain.get_hash() for slot in curr.finished_sub_slots]
                    )
                if curr.height == 0:
                    return constants.GENESIS_CHALLENGE

                curr = all_blocks.get(curr.prev_header_hash, None)
            challenge = reversed_challenge_hashes[challenges_to_look_for - 1]
    return challenge


def last_change_height_cs(cs: CoinState) -> uint32:
    if cs.spent_height is not None:
        return cs.spent_height
    if cs.created_height is not None:
        return cs.created_height

    # Reorgs should be processed at the beginning
    return uint32(0)


async def _fetch_header_blocks_inner(
    all_peers: List[WSChiaConnection],
    request: RequestHeaderBlocks,
) -> Optional[RespondHeaderBlocks]:
    # We will modify this list, don't modify passed parameters.
    remaining_peers = list(all_peers)

    while len(remaining_peers) > 0:
        peer = random.choice(remaining_peers)

        response = await peer.request_header_blocks(request)

        if isinstance(response, RespondHeaderBlocks):
            return response

        # Request to peer failed in some way, close the connection and remove the peer
        # from our local list.
        await peer.close()
        remaining_peers.remove(peer)

    return None


async def fetch_header_blocks_in_range(
    start: uint32,
    end: uint32,
    peer_request_cache: PeerRequestCache,
    all_peers: List[WSChiaConnection],
) -> Optional[List[HeaderBlock]]:
    blocks: List[HeaderBlock] = []
    for i in range(start - (start % 32), end + 1, 32):
        request_start = min(uint32(i), end)
        request_end = min(uint32(i + 31), end)
        res_h_blocks_task: Optional[asyncio.Task] = peer_request_cache.get_block_request(request_start, request_end)

        if res_h_blocks_task is not None:
            log.debug(f"Using cache for: {start}-{end}")
            if res_h_blocks_task.done():
                res_h_blocks: Optional[RespondHeaderBlocks] = res_h_blocks_task.result()
            else:
                res_h_blocks = await res_h_blocks_task
        else:
            log.debug(f"Fetching: {start}-{end}")
            request_header_blocks = RequestHeaderBlocks(request_start, request_end)
            res_h_blocks_task = asyncio.create_task(_fetch_header_blocks_inner(all_peers, request_header_blocks))
            peer_request_cache.add_to_block_requests(request_start, request_end, res_h_blocks_task)
            res_h_blocks = await res_h_blocks_task
        if res_h_blocks is None:
            return None
        assert res_h_blocks is not None
        blocks.extend([bl for bl in res_h_blocks.header_blocks if bl.height >= start])
    return blocks
