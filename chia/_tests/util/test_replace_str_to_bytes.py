from __future__ import annotations

import pytest
from chia_rs import ConsensusConstants

from chia.consensus.constants import replace_str_to_bytes
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64, uint128

AGG_SIG_DATA = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")

test_constants = ConsensusConstants(
    SLOT_BLOCKS_TARGET=uint32(32),
    MIN_BLOCKS_PER_CHALLENGE_BLOCK=uint8(16),
    MAX_SUB_SLOT_BLOCKS=uint32(128),
    NUM_SPS_SUB_SLOT=uint32(64),
    SUB_SLOT_ITERS_STARTING=uint64(2**27),
    DIFFICULTY_CONSTANT_FACTOR=uint128(2**67),
    DIFFICULTY_STARTING=uint64(7),
    DIFFICULTY_CHANGE_MAX_FACTOR=uint32(3),
    SUB_EPOCH_BLOCKS=uint32(384),
    EPOCH_BLOCKS=uint32(4608),
    SIGNIFICANT_BITS=uint8(8),
    DISCRIMINANT_SIZE_BITS=uint16(1024),
    NUMBER_ZERO_BITS_PLOT_FILTER=uint8(9),
    MIN_PLOT_SIZE=uint8(32),
    MAX_PLOT_SIZE=uint8(50),
    SUB_SLOT_TIME_TARGET=uint16(600),
    NUM_SP_INTERVALS_EXTRA=uint8(3),
    MAX_FUTURE_TIME2=uint32(2 * 60),
    NUMBER_OF_TIMESTAMPS=uint8(11),
    GENESIS_CHALLENGE=bytes32.fromhex("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    AGG_SIG_ME_ADDITIONAL_DATA=AGG_SIG_DATA,
    AGG_SIG_PARENT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([43])),
    AGG_SIG_PUZZLE_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([44])),
    AGG_SIG_AMOUNT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([45])),
    AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([46])),
    AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([47])),
    AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([48])),
    GENESIS_PRE_FARM_POOL_PUZZLE_HASH=bytes32.fromhex(
        "d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"
    ),
    GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bytes32.fromhex(
        "3d8765d3a597ec1d99663f6c9816d915b9f68613ac94009884c4addaefcce6af"
    ),
    MAX_VDF_WITNESS_SIZE=uint8(64),
    MEMPOOL_BLOCK_BUFFER=uint8(10),
    MAX_COIN_AMOUNT=uint64((1 << 64) - 1),
    MAX_BLOCK_COST_CLVM=uint64(11000000000),
    COST_PER_BYTE=uint64(12000),
    WEIGHT_PROOF_THRESHOLD=uint8(2),
    BLOCKS_CACHE_SIZE=uint32(4608 + (128 * 4)),
    WEIGHT_PROOF_RECENT_BLOCKS=uint32(1000),
    MAX_BLOCK_COUNT_PER_REQUESTS=uint32(32),
    MAX_GENERATOR_SIZE=uint32(1000000),
    MAX_GENERATOR_REF_LIST_SIZE=uint32(512),
    POOL_SUB_SLOT_ITERS=uint64(37600000000),
    SOFT_FORK5_HEIGHT=uint32(5940000),
    HARD_FORK_HEIGHT=uint32(5496000),
    PLOT_FILTER_128_HEIGHT=uint32(10542000),
    PLOT_FILTER_64_HEIGHT=uint32(15592000),
    PLOT_FILTER_32_HEIGHT=uint32(20643000),
)


def test_replace_str_to_bytes() -> None:
    test2 = replace_str_to_bytes(
        test_constants,
        GENESIS_PRE_FARM_FARMER_PUZZLE_HASH="0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    )
    assert test2 == test_constants.replace(
        GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bytes32.fromhex(
            "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        )
    )
    assert test2.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH == bytes32.fromhex(
        "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )


def test_replace_str_to_bytes_additional_data() -> None:
    test2 = replace_str_to_bytes(
        test_constants,
        AGG_SIG_ME_ADDITIONAL_DATA="0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    )

    # if we update AGG_SIG_ME_ADDITIONAL_DATA, the other additional data is also
    # updated

    AGG_SIG_DATA = bytes32.fromhex("cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc")
    assert test2 == replace_str_to_bytes(
        test_constants,
        AGG_SIG_ME_ADDITIONAL_DATA="0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        AGG_SIG_PARENT_ADDITIONAL_DATA="0x" + std_hash(AGG_SIG_DATA + bytes([43])).hex(),
        AGG_SIG_PUZZLE_ADDITIONAL_DATA="0x" + std_hash(AGG_SIG_DATA + bytes([44])).hex(),
        AGG_SIG_AMOUNT_ADDITIONAL_DATA="0x" + std_hash(AGG_SIG_DATA + bytes([45])).hex(),
        AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA="0x" + std_hash(AGG_SIG_DATA + bytes([46])).hex(),
        AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA="0x" + std_hash(AGG_SIG_DATA + bytes([47])).hex(),
        AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA="0x" + std_hash(AGG_SIG_DATA + bytes([48])).hex(),
    )


def test_replace_str_to_bytes_none() -> None:
    test2 = replace_str_to_bytes(test_constants)
    assert test2 == test_constants


def test_replace_str_to_bytes_uint8() -> None:
    test2 = replace_str_to_bytes(test_constants, MIN_BLOCKS_PER_CHALLENGE_BLOCK=uint8(8))
    assert test2 == test_constants.replace(MIN_BLOCKS_PER_CHALLENGE_BLOCK=uint8(8))
    assert test2.MIN_BLOCKS_PER_CHALLENGE_BLOCK == 8


def test_replace_str_to_bytes_invalid_field(caplog: pytest.LogCaptureFixture) -> None:
    # invalid field
    test2 = replace_str_to_bytes(
        test_constants, FOOBAR="0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    assert test2 == test_constants
    assert 'invalid key in network configuration (config.yaml) "FOOBAR". Ignoring' in caplog.text


def test_replace_str_to_bytes_deprecated_field(caplog: pytest.LogCaptureFixture) -> None:
    # invalid, but deprecated, field. We don't warn on it
    test2 = replace_str_to_bytes(test_constants, NETWORK_TYPE=1)
    assert test2 == test_constants
    assert caplog.text == ""


def test_replace_str_to_bytes_invalid_value() -> None:
    # invalid value
    with pytest.raises(ValueError, match="non-hexadecimal number found in"):
        replace_str_to_bytes(
            test_constants,
            GENESIS_PRE_FARM_FARMER_PUZZLE_HASH="fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        )
