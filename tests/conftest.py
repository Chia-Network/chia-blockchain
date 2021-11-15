import pytest

from tests.block_tools import BlockTools
from tests.setup_nodes import setup_shared_block_tools_and_keyring
from tests.util.keyring import TempKeyring
from typing import Optional


# TODO: tests.setup_nodes (which is also imported by tests.util.blockchain) creates a
#       global BlockTools at tests.setup_nodes.bt.  This results in an attempt to create
#       the chia root directory which the build scripts symlink to a sometimes-not-there
#       directory.  When not there Python complains since, well, the symlink is a file
#       not a directory and also not pointing to a directory.  In those same cases,
#       these fixtures are not used.  It would be good to refactor that global state
#       creation, including the filesystem modification, away from the import but
#       that seems like a separate step and until then locating the imports in the
#       fixtures avoids the issue.


class BlockToolsFixtureHelper:
    def __init__(self, block_tools: BlockTools, keyring: TempKeyring) -> None:
        self.block_tools: BlockTools = block_tools
        self.keyring: TempKeyring = keyring
        self.cleaned_up: bool = False

    def cleanup(self) -> None:
        assert self.cleaned_up is False
        if self.keyring is not None:
            self.keyring.cleanup()
        self.cleaned_up = True


shared_block_tools_helper: Optional[BlockToolsFixtureHelper] = None


def get_shared_block_tools_helper() -> BlockToolsFixtureHelper:
    global shared_block_tools_helper
    if shared_block_tools_helper is None:
        b_tools, keyring = setup_shared_block_tools_and_keyring()
        shared_block_tools_helper = BlockToolsFixtureHelper(b_tools, keyring)
    return shared_block_tools_helper


@pytest.fixture(scope="module")
def cleanup_shared_block_tools(request) -> None:
    """
    This fixture is run once per module and is used to clean up the shared block tools
    after all tests in the module have run.
    """

    def cleanup():
        get_shared_block_tools_helper().cleanup()

    request.addfinalizer(cleanup)


@pytest.fixture(scope="module")
def shared_b_tools(cleanup_shared_block_tools) -> BlockTools:
    """
    This fixture is run once per module and is used to create the shared block tools
    for all tests in the module.
    """
    return get_shared_block_tools_helper().block_tools


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


@pytest.fixture(scope="module")
async def default_400_blocks(shared_b_tools):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(400, f"test_blocks_400_{block_format_version}.db", shared_b_tools, seed=b"alternate2")


@pytest.fixture(scope="module")
async def default_1000_blocks(shared_b_tools):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(1000, f"test_blocks_1000_{block_format_version}.db", shared_b_tools)


@pytest.fixture(scope="module")
async def pre_genesis_empty_slots_1000_blocks(shared_b_tools):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        1000,
        f"pre_genesis_empty_slots_1000_blocks{block_format_version}.db",
        shared_b_tools,
        seed=b"alternate2",
        empty_sub_slots=1,
    )


@pytest.fixture(scope="module")
async def default_10000_blocks(shared_b_tools):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(10000, f"test_blocks_10000_{block_format_version}.db", shared_b_tools)


@pytest.fixture(scope="module")
async def default_20000_blocks(shared_b_tools):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(20000, f"test_blocks_20000_{block_format_version}.db", shared_b_tools)


@pytest.fixture(scope="module")
async def default_10000_blocks_compact(shared_b_tools):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        10000,
        f"test_blocks_10000_compact_{block_format_version}.db",
        shared_b_tools,
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
    )


@pytest.fixture(scope="function")
async def get_temp_keyring():
    with TempKeyring() as keychain:
        yield keychain
