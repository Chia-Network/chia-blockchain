from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from blspy import G1Element, G2Element
from chia_rs import serialized_length
from chiabip158 import PyBIP158

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import TransactionsInfo
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32


def skip_list(buf: memoryview, skip_item: Callable[[memoryview], memoryview]) -> memoryview:
    n = int.from_bytes(buf[:4], "big", signed=False)
    buf = buf[4:]
    for _ in range(n):
        buf = skip_item(buf)
    return buf


def skip_bytes(buf: memoryview) -> memoryview:
    n = int.from_bytes(buf[:4], "big", signed=False)
    buf = buf[4:]
    assert n >= 0
    return buf[n:]


def skip_optional(buf: memoryview, skip_item: Callable[[memoryview], memoryview]) -> memoryview:
    if buf[0] == 0:
        return buf[1:]
    assert buf[0] == 1
    return skip_item(buf[1:])


def skip_bytes32(buf: memoryview) -> memoryview:
    return buf[32:]


def skip_uint32(buf: memoryview) -> memoryview:
    return buf[4:]


def skip_uint64(buf: memoryview) -> memoryview:
    return buf[8:]


def skip_uint128(buf: memoryview) -> memoryview:
    return buf[16:]


def skip_uint8(buf: memoryview) -> memoryview:
    return buf[1:]


def skip_bool(buf: memoryview) -> memoryview:
    assert buf[0] in [0, 1]
    return buf[1:]


# def skip_class_group_element(buf: memoryview) -> memoryview:
#    return buf[100:]  # bytes100


def skip_vdf_info(buf: memoryview) -> memoryview:
    #    buf = skip_bytes32(buf)
    #    buf = skip_uint64(buf)
    #    return skip_class_group_element(buf)
    return buf[32 + 8 + 100 :]


def skip_vdf_proof(buf: memoryview) -> memoryview:
    buf = skip_uint8(buf)  # witness_type
    buf = skip_bytes(buf)  # witness
    return skip_bool(buf)  # normalized_to_identity


def skip_challenge_chain_sub_slot(buf: memoryview) -> memoryview:
    buf = skip_vdf_info(buf)
    buf = skip_optional(buf, skip_bytes32)  # infused challenge chain sub skit hash
    buf = skip_optional(buf, skip_bytes32)  # subepoch_summary_hash
    buf = skip_optional(buf, skip_uint64)  # new_sub_slot_iters
    return skip_optional(buf, skip_uint64)  # new_difficulty


def skip_infused_challenge_chain(buf: memoryview) -> memoryview:
    return skip_vdf_info(buf)  # infused_challenge_chain_end_of_slot_vdf


def skip_reward_chain_sub_slot(buf: memoryview) -> memoryview:
    buf = skip_vdf_info(buf)  # end_of_slot_vdf
    buf = skip_bytes32(buf)  # challenge_chain_sub_slot_hash
    buf = skip_optional(buf, skip_bytes32)  # infused_challenge_chain_sub_slot_hash
    return skip_uint8(buf)


def skip_sub_slot_proofs(buf: memoryview) -> memoryview:
    buf = skip_vdf_proof(buf)  # challenge_chain_slot_proof
    buf = skip_optional(buf, skip_vdf_proof)  # infused_challenge_chain_slot_proof
    return skip_vdf_proof(buf)  # reward_chain_slot_proof


def skip_end_of_sub_slot_bundle(buf: memoryview) -> memoryview:
    buf = skip_challenge_chain_sub_slot(buf)
    buf = skip_optional(buf, skip_infused_challenge_chain)
    buf = skip_reward_chain_sub_slot(buf)
    return skip_sub_slot_proofs(buf)


def skip_g1_element(buf: memoryview) -> memoryview:
    return buf[G1Element.SIZE :]


def skip_g2_element(buf: memoryview) -> memoryview:
    return buf[G2Element.SIZE :]


def skip_proof_of_space(buf: memoryview) -> memoryview:
    buf = skip_bytes32(buf)  # challenge
    buf = skip_optional(buf, skip_g1_element)  # pool_public_key
    buf = skip_optional(buf, skip_bytes32)  # pool_contract_puzzle_hash
    buf = skip_g1_element(buf)  # plot_public_key
    buf = skip_uint8(buf)  # size
    return skip_bytes(buf)  # proof


def skip_reward_chain_block(buf: memoryview) -> memoryview:
    buf = skip_uint128(buf)  # weight
    buf = skip_uint32(buf)  # height
    buf = skip_uint128(buf)  # total_iters
    buf = skip_uint8(buf)  # signage_point_index
    buf = skip_bytes32(buf)  # pos_ss_cc_challenge_hash

    buf = skip_proof_of_space(buf)  # proof_of_space
    buf = skip_optional(buf, skip_vdf_info)  # challenge_chain_sp_vdf
    buf = skip_g2_element(buf)  # challenge_chain_sp_signature
    buf = skip_vdf_info(buf)  # challenge_chain_ip_vdf
    buf = skip_optional(buf, skip_vdf_info)  # reward_chain_sp_vdf
    buf = skip_g2_element(buf)  # reward_chain_sp_signature
    buf = skip_vdf_info(buf)  # reward_chain_ip_vdf
    buf = skip_optional(buf, skip_vdf_info)  # infused_challenge_chain_ip_vdf
    return skip_bool(buf)  # is_transaction_block


def skip_pool_target(buf: memoryview) -> memoryview:
    # buf = skip_bytes32(buf)  # puzzle_hash
    # return skip_uint32(buf)  # max_height
    return buf[32 + 4 :]


def skip_foliage_block_data(buf: memoryview) -> memoryview:
    buf = skip_bytes32(buf)  # unfinished_reward_block_hash
    buf = skip_pool_target(buf)  # pool_target
    buf = skip_optional(buf, skip_g2_element)  # pool_signature
    buf = skip_bytes32(buf)  # farmer_reward_puzzle_hash
    return skip_bytes32(buf)  # extension_data


def skip_foliage(buf: memoryview) -> memoryview:
    buf = skip_bytes32(buf)  # prev_block_hash
    buf = skip_bytes32(buf)  # reward_block_hash
    buf = skip_foliage_block_data(buf)  # foliage_block_data
    buf = skip_g2_element(buf)  # foliage_block_data_signature
    buf = skip_optional(buf, skip_bytes32)  # foliage_transaction_block_hash
    return skip_optional(buf, skip_g2_element)  # foliage_transaction_block_signature


def prev_hash_from_foliage(buf: memoryview) -> Tuple[memoryview, bytes32]:
    prev_hash = buf[:32]  # prev_block_hash
    buf = skip_bytes32(buf)  # prev_block_hash
    buf = skip_bytes32(buf)  # reward_block_hash
    buf = skip_foliage_block_data(buf)  # foliage_block_data
    buf = skip_g2_element(buf)  # foliage_block_data_signature
    buf = skip_optional(buf, skip_bytes32)  # foliage_transaction_block_hash
    return skip_optional(buf, skip_g2_element), bytes32(prev_hash)  # foliage_transaction_block_signature


def skip_foliage_transaction_block(buf: memoryview) -> memoryview:
    # buf = skip_bytes32(buf)  # prev_transaction_block_hash
    # buf = skip_uint64(buf)  # timestamp
    # buf = skip_bytes32(buf)  # filter_hash
    # buf = skip_bytes32(buf)  # additions_root
    # buf = skip_bytes32(buf)  # removals_root
    # return skip_bytes32(buf)  # transactions_info_hash
    return buf[32 + 8 + 32 + 32 + 32 + 32 :]


def skip_coin(buf: memoryview) -> memoryview:
    # buf = skip_bytes32(buf)  # parent_coin_info
    # buf = skip_bytes32(buf)  # puzzle_hash
    # return skip_uint64(buf)  # amount
    return buf[32 + 32 + 8 :]


def skip_transactions_info(buf: memoryview) -> memoryview:
    # buf = skip_bytes32(buf)  # generator_root
    # buf = skip_bytes32(buf)  # generator_refs_root
    # buf = skip_g2_element(buf)  # aggregated_signature
    # buf = skip_uint64(buf)  # fees
    # buf = skip_uint64(buf)  # cost
    buf = buf[32 + 32 + G2Element.SIZE + 8 + 8 :]
    return skip_list(buf, skip_coin)


def generator_from_block(buf: memoryview) -> Optional[SerializedProgram]:
    buf = skip_list(buf, skip_end_of_sub_slot_bundle)  # finished_sub_slots
    buf = skip_reward_chain_block(buf)  # reward_chain_block
    buf = skip_optional(buf, skip_vdf_proof)  # challenge_chain_sp_proof
    buf = skip_vdf_proof(buf)  # challenge_chain_ip_proof
    buf = skip_optional(buf, skip_vdf_proof)  # reward_chain_sp_proof
    buf = skip_vdf_proof(buf)  # reward_chain_ip_proof
    buf = skip_optional(buf, skip_vdf_proof)  # infused_challenge_chain_ip_proof
    buf = skip_foliage(buf)  # foliage
    buf = skip_optional(buf, skip_foliage_transaction_block)  # foliage_transaction_block
    buf = skip_optional(buf, skip_transactions_info)  # transactions_info

    # this is the transactions_generator optional
    if buf[0] == 0:
        return None

    buf = buf[1:]
    length = serialized_length(buf)
    return SerializedProgram.from_bytes(bytes(buf[:length]))


# this implements the BlockInfo protocol
@dataclass(frozen=True)
class GeneratorBlockInfo:
    prev_header_hash: bytes32
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: List[uint32]


def block_info_from_block(buf: memoryview) -> GeneratorBlockInfo:
    buf = skip_list(buf, skip_end_of_sub_slot_bundle)  # finished_sub_slots
    buf = skip_reward_chain_block(buf)  # reward_chain_block
    buf = skip_optional(buf, skip_vdf_proof)  # challenge_chain_sp_proof
    buf = skip_vdf_proof(buf)  # challenge_chain_ip_proof
    buf = skip_optional(buf, skip_vdf_proof)  # reward_chain_sp_proof
    buf = skip_vdf_proof(buf)  # reward_chain_ip_proof
    buf = skip_optional(buf, skip_vdf_proof)  # infused_challenge_chain_ip_proof
    buf, prev_hash = prev_hash_from_foliage(buf)  # foliage
    buf = skip_optional(buf, skip_foliage_transaction_block)  # foliage_transaction_block
    buf = skip_optional(buf, skip_transactions_info)  # transactions_info

    # this is the transactions_generator optional
    generator = None
    if buf[0] != 0:
        buf = buf[1:]
        length = serialized_length(buf)
        generator = SerializedProgram.from_bytes(bytes(buf[:length]))
        buf = buf[length:]
    else:
        buf = buf[1:]

    refs_length = uint32.from_bytes(buf[:4])
    buf = buf[4:]

    refs = []
    for i in range(refs_length):
        refs.append(uint32.from_bytes(buf[:4]))
        buf = buf[4:]

    return GeneratorBlockInfo(prev_hash, generator, refs)


def header_block_from_block(
    buf: memoryview, request_filter: bool = True, tx_addition_coins: List[Coin] = [], removal_names: List[bytes32] = []
) -> bytes:
    buf2 = buf[:]
    buf2 = skip_list(buf2, skip_end_of_sub_slot_bundle)  # finished_sub_slots
    buf2 = skip_reward_chain_block(buf2)  # reward_chain_block
    buf2 = skip_optional(buf2, skip_vdf_proof)  # challenge_chain_sp_proof
    buf2 = skip_vdf_proof(buf2)  # challenge_chain_ip_proof
    buf2 = skip_optional(buf2, skip_vdf_proof)  # reward_chain_sp_proof
    buf2 = skip_vdf_proof(buf2)  # reward_chain_ip_proof
    buf2 = skip_optional(buf2, skip_vdf_proof)  # infused_challenge_chain_ip_proof
    buf2 = skip_foliage(buf2)  # foliage
    if buf2[0] == 0:
        is_transaction_block = False
    else:
        is_transaction_block = True

    buf2 = skip_optional(buf2, skip_foliage_transaction_block)  # foliage_transaction_block

    transactions_info: Optional[TransactionsInfo] = None
    # we make it optional even if it's not by default
    # if request_filter is True it will read extra bytes and populate it properly
    transactions_info_optional: bytes = bytes([0])
    encoded_filter = b"\x00"

    if request_filter:
        # this is the transactions_info optional
        if buf2[0] == 0:
            transactions_info_optional = bytes([0])
        else:
            transactions_info_optional = bytes([1])
            buf3 = buf2[1:]
            transactions_info = TransactionsInfo.parse(io.BytesIO(buf3))
        byte_array_tx: List[bytearray] = []
        if is_transaction_block and transactions_info:
            addition_coins = tx_addition_coins + list(transactions_info.reward_claims_incorporated)
            for coin in addition_coins:
                byte_array_tx.append(bytearray(coin.puzzle_hash))
            for name in removal_names:
                byte_array_tx.append(bytearray(name))

        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded_filter = bytes(bip158.GetEncoded())

    # Takes everything up to but not including transactions info
    header_block: bytes = bytes(buf[: (len(buf) - len(buf2))])
    # Transactions filter, potentially with added / removal coins
    header_block += (len(encoded_filter)).to_bytes(4, "big") + encoded_filter
    # Add transactions info
    header_block += transactions_info_optional
    if transactions_info is not None:
        header_block += bytes(transactions_info)

    return header_block
