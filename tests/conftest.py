import pytest

from tests.util.blockchain import create_blockchain, persistent_blocks


@pytest.fixture(scope="function")
async def empty_blockchain():
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    from tests.setup_nodes import test_constants

    bc1, connection, db_path = await create_blockchain(test_constants)
    yield bc1

    await connection.close()
    bc1.shut_down()
    db_path.unlink()


block_format_version = "rc4"


@pytest.fixture(scope="session")
async def default_400_blocks():
    return persistent_blocks(400, f"test_blocks_400_{block_format_version}.db", seed=b"alternate2")


@pytest.fixture(scope="session")
async def default_1000_blocks():
    return persistent_blocks(1000, f"test_blocks_1000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def pre_genesis_empty_slots_1000_blocks():
    return persistent_blocks(
        1000, f"pre_genesis_empty_slots_1000_blocks{block_format_version}.db", seed=b"alternate2", empty_sub_slots=1
    )


@pytest.fixture(scope="session")
async def default_10000_blocks():
    return persistent_blocks(10000, f"test_blocks_10000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def default_20000_blocks():
    return persistent_blocks(20000, f"test_blocks_20000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def default_10000_blocks_compact():
    return persistent_blocks(
        10000,
        f"test_blocks_10000_compact_{block_format_version}.db",
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
    )
