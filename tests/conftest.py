import asyncio

import pytest


# TODO: tests.setup_nodes (which is also imported by tests.util.blockchain) creates a
#       global BlockTools at tests.setup_nodes.bt.  This results in an attempt to create
#       the chia root directory which the build scripts symlink to a sometimes-not-there
#       directory.  When not there Python complains since, well, the symlink is a file
#       not a directory and also not pointing to a directory.  In those same cases,
#       these fixtures are not used.  It would be good to refactor that global state
#       creation, including the filesystem modification, away from the import but
#       that seems like a separate step and until then locating the imports in the
#       fixtures avoids the issue.


# https://github.com/pytest-dev/pytest-asyncio/blob/f21e0da345f877755b89ff87b6dcea70815b4497/pytest_asyncio/plugin.py#L224-L229
# https://github.com/pytest-dev/pytest-asyncio/blob/master/LICENSE ( Apache License 2.0 )
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def empty_blockchain():
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    from tests.util.blockchain import create_blockchain
    from tests.setup_nodes import test_constants

    bc1, connection, db_path = await create_blockchain(test_constants)
    yield bc1

    await connection.close()
    bc1.shut_down()
    db_path.unlink()


block_format_version = "rc4"


@pytest.fixture(scope="session")
async def default_400_blocks():
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(400, f"test_blocks_400_{block_format_version}.db", seed=b"alternate2")


@pytest.fixture(scope="session")
async def default_1000_blocks():
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(1000, f"test_blocks_1000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def pre_genesis_empty_slots_1000_blocks():
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        1000, f"pre_genesis_empty_slots_1000_blocks{block_format_version}.db", seed=b"alternate2", empty_sub_slots=1
    )


@pytest.fixture(scope="session")
async def default_10000_blocks():
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(10000, f"test_blocks_10000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def default_20000_blocks():
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(20000, f"test_blocks_20000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def default_10000_blocks_compact():
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        10000,
        f"test_blocks_10000_compact_{block_format_version}.db",
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
    )
