from __future__ import annotations

import random

import importlib_resources
from chia_rs import (
    AugSchemeMPL,
    ClassgroupElement,
    Coin,
    Foliage,
    FoliageBlockData,
    FoliageTransactionBlock,
    FullBlock,
    G1Element,
    G2Element,
    PoolTarget,
    ProofOfSpace,
    RewardChainBlock,
    TransactionsInfo,
    VDFInfo,
    VDFProof,
)
from chia_rs.sized_bytes import bytes32, bytes100
from chia_rs.sized_ints import uint8, uint32, uint64, uint128

from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.serialized_program import SerializedProgram

# farmer puzzle hash
ph = bytes32(b"a" * 32)

clvm_generator_bin_path = importlib_resources.files(__name__.rpartition(".")[0]).joinpath("clvm_generator.bin")
clvm_generator = clvm_generator_bin_path.read_bytes()


def rewards(height: uint32) -> tuple[Coin, Coin]:
    farmer_coin = create_farmer_coin(height, ph, uint64(250000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    pool_coin = create_pool_coin(height, ph, uint64(1750000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    return farmer_coin, pool_coin


def rand_hash() -> bytes32:
    return bytes32.random()


def rand_g1() -> G1Element:
    sk = AugSchemeMPL.key_gen(random.randbytes(96))
    return sk.get_g1()


def rand_g2() -> G2Element:
    sk = AugSchemeMPL.key_gen(random.randbytes(96))
    return AugSchemeMPL.sign(sk, b"foobar")


def rand_class_group_element() -> ClassgroupElement:
    return ClassgroupElement(bytes100.random())


def rand_vdf() -> VDFInfo:
    return VDFInfo(rand_hash(), uint64(random.randint(100000, 1000000000)), rand_class_group_element())


def rand_vdf_proof() -> VDFProof:
    return VDFProof(
        uint8(1),  # witness_type
        rand_hash(),  # witness
        bool(random.randint(0, 1)),  # normalized_to_identity
    )


def rand_full_block() -> FullBlock:
    proof_of_space = ProofOfSpace(
        rand_hash(),
        rand_g1(),
        None,
        rand_g1(),
        uint8(0),
        random.randbytes(8 * 32),
    )

    reward_chain_block = RewardChainBlock(
        uint128(1),
        uint32(2),
        uint128(3),
        uint8(4),
        rand_hash(),
        proof_of_space,
        None,
        rand_g2(),
        rand_vdf(),
        None,
        rand_g2(),
        rand_vdf(),
        rand_vdf(),
        True,
    )

    pool_target = PoolTarget(
        rand_hash(),
        uint32(0),
    )

    foliage_block_data = FoliageBlockData(
        rand_hash(),
        pool_target,
        rand_g2(),
        rand_hash(),
        rand_hash(),
    )

    foliage = Foliage(
        rand_hash(),
        rand_hash(),
        foliage_block_data,
        rand_g2(),
        rand_hash(),
        rand_g2(),
    )

    foliage_transaction_block = FoliageTransactionBlock(
        rand_hash(),
        uint64(0),
        rand_hash(),
        rand_hash(),
        rand_hash(),
        rand_hash(),
    )

    farmer_coin, pool_coin = rewards(uint32(0))

    transactions_info = TransactionsInfo(
        rand_hash(),
        rand_hash(),
        rand_g2(),
        uint64(0),
        uint64(1),
        [farmer_coin, pool_coin],
    )

    full_block = FullBlock(
        [],
        reward_chain_block,
        rand_vdf_proof(),
        rand_vdf_proof(),
        rand_vdf_proof(),
        rand_vdf_proof(),
        rand_vdf_proof(),
        foliage,
        foliage_transaction_block,
        transactions_info,
        SerializedProgram.from_bytes(clvm_generator),
        [],
    )

    return full_block
