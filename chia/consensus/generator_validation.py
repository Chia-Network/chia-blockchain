from __future__ import annotations

from chia_rs import (
    INTERNED_SPEND_LIST,
    ConsensusConstants,
    FullBlock,
    UnfinishedBlock,
    get_flags_for_height_and_constants,
    tree_hash_2026,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.block_generator_info import block_has_transactions_generator, get_transactions_generator_bytes
from chia.types.block_protocol import BlockInfo
from chia.util.errors import Err
from chia.util.hash import std_hash


def generator_refs_root(generator_refs: list[uint32]) -> bytes:
    """The `generator_refs_root` committed in the transactions info for this ref list."""
    if generator_refs == []:
        return bytes([1] * 32)
    return std_hash(b"".join(i.stream_to_bytes() for i in generator_refs))


def validate_generator_ref_list(
    constants: ConsensusConstants,
    block: FullBlock | UnfinishedBlock,
    height: uint32,
    prev_transaction_block_height: uint32,
) -> Err | None:
    assert block.transactions_info is not None

    generator_refs = block.transactions_generator_ref_list
    if generator_refs == []:
        if block.transactions_info.generator_refs_root != generator_refs_root(generator_refs):
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
        return None

    if prev_transaction_block_height >= constants.SOFT_FORK9_HEIGHT:
        return Err.TOO_MANY_GENERATOR_REFS
    if not block_has_transactions_generator(block):
        return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
    if len(generator_refs) > constants.MAX_GENERATOR_REF_LIST_SIZE:
        return Err.TOO_MANY_GENERATOR_REFS
    if block.transactions_info.generator_refs_root != generator_refs_root(generator_refs):
        return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
    if any(index >= height for index in generator_refs):
        return Err.FUTURE_GENERATOR_REFS

    return None


def validate_tx_generator(
    constants: ConsensusConstants,
    block: BlockInfo,
    pre_sp_tx_height: uint32,
) -> Err | None:
    # Validate block version. Version 1 (plain generator buffer, no ref list) is required
    # after the 3.0 hard fork, and version 0 is required before it. Activation is based on
    # pre_sp_tx_block_height (0 for genesis), matching unfinished-header validation.
    if block.version == 1:
        if pre_sp_tx_height < constants.HARD_FORK2_HEIGHT:
            return Err.INVALID_BLOCK_VERSION
    elif block.version == 0:
        if pre_sp_tx_height >= constants.HARD_FORK2_HEIGHT:
            return Err.INVALID_BLOCK_VERSION
    else:
        return Err.INVALID_BLOCK_VERSION
    return None


def compute_generator_root(generator: bytes, flags: int) -> bytes32:
    """Commit to the interned tree after activation, or serialized bytes before it."""
    if flags & INTERNED_SPEND_LIST:
        return tree_hash_2026(generator)
    return std_hash(generator)


def validate_generator_root(
    generator: bytes, root: bytes32, constants: ConsensusConstants, pre_sp_tx_height: uint32
) -> bool:
    try:
        flags = get_flags_for_height_and_constants(pre_sp_tx_height, constants)
        return compute_generator_root(generator, flags) == root
    except ValueError:
        # Malformed interned trees cannot match a generator commitment.
        return False


def validate_committed_generator(
    block: FullBlock, constants: ConsensusConstants, pre_sp_tx_height: uint32
) -> Err | None:
    """
    Check, without running it, that the generator of transaction block `block`
    is the one its header hash commits to (foliage -> foliage transaction
    block -> transactions info -> generator root). A peer can keep every
    farmed/signed header field intact and swap only the generator.
    """
    assert block.transactions_info is not None
    if block.foliage_transaction_block is None:
        return Err.INVALID_TRANSACTIONS_INFO_HASH
    generator_bytes = get_transactions_generator_bytes(block)
    if generator_bytes is None:
        if block.transactions_info.generator_root != bytes([0] * 32):
            return Err.INVALID_TRANSACTIONS_GENERATOR_HASH
    elif not validate_generator_root(
        generator_bytes, block.transactions_info.generator_root, constants, pre_sp_tx_height
    ):
        return Err.INVALID_TRANSACTIONS_GENERATOR_HASH
    if block.foliage_transaction_block.transactions_info_hash != block.transactions_info.get_hash():
        return Err.INVALID_TRANSACTIONS_INFO_HASH
    if block.foliage.foliage_transaction_block_hash != block.foliage_transaction_block.get_hash():
        return Err.INVALID_FOLIAGE_BLOCK_HASH
    return None


def validate_committed_body(block: FullBlock, constants: ConsensusConstants, pre_sp_tx_height: uint32) -> Err | None:
    """
    Check, without running anything, that the body of `block` (transactions
    info, generator and generator ref list) is the one its header hash commits
    to. For replaying a block whose header hash is already known but whose
    body was supplied by a peer.
    """
    if block.foliage.foliage_transaction_block_hash is None:
        if (
            block.foliage_transaction_block is not None
            or block.transactions_info is not None
            or block_has_transactions_generator(block)
            or block.transactions_generator_ref_list != []
        ):
            return Err.NOT_BLOCK_BUT_HAS_DATA
        return None
    if block.transactions_info is None:
        return Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA
    generator_error = validate_committed_generator(block, constants, pre_sp_tx_height)
    if generator_error is not None:
        return generator_error
    if block.transactions_info.generator_refs_root != generator_refs_root(block.transactions_generator_ref_list):
        return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
    return None
