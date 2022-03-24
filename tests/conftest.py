# flake8: noqa E402 # See imports after multiprocessing.set_start_method
import multiprocessing
import os
import pytest
import pytest_asyncio
import tempfile

from tests.setup_nodes import setup_node_and_wallet, setup_n_nodes, setup_two_nodes

# Set spawn after stdlib imports, but before other imports
multiprocessing.set_start_method("spawn")

from pathlib import Path
from chia.util.keyring_wrapper import KeyringWrapper
from tests.block_tools import BlockTools, test_constants, create_block_tools
from tests.util.keyring import TempKeyring


@pytest.fixture(scope="session")
def get_keychain():
    with TempKeyring() as keychain:
        yield keychain
        KeyringWrapper.cleanup_shared_instance()


@pytest.fixture(scope="session", name="bt")
def block_tools_fixture(get_keychain) -> BlockTools:
    # Note that this causes a lot of CPU and disk traffic - disk, DB, ports, process creation ...
    _shared_block_tools = create_block_tools(constants=test_constants, keychain=get_keychain)
    return _shared_block_tools


# if you have a system that has an unusual hostname for localhost and you want
# to run the tests, change the `self_hostname` fixture
@pytest_asyncio.fixture(scope="session")
def self_hostname():
    return "localhost"


# NOTE:
#       Instantiating the bt fixture results in an attempt to create the chia root directory
#       which the build scripts symlink to a sometimes-not-there directory.
#       When not there, Python complains since, well, the symlink is not a directory nor points to a directory.
#
#       Now that we have removed the global at tests.setup_nodes.bt, we can move the imports out of
#       the fixtures below. Just be aware of the filesystem modification during bt fixture creation


@pytest_asyncio.fixture(scope="function", params=[1, 2])
async def empty_blockchain(request):
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    from tests.util.blockchain import create_blockchain
    from tests.setup_nodes import test_constants

    bc1, connection, db_path = await create_blockchain(test_constants, request.param)
    yield bc1

    await connection.close()
    bc1.shut_down()
    db_path.unlink()


@pytest.fixture(scope="function", params=[1, 2])
def db_version(request):
    return request.param


@pytest.fixture(scope="function", params=[1000000, 2300000])
def softfork_height(request):
    return request.param


block_format_version = "rc4"


@pytest.fixture(scope="session")
def default_400_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(400, f"test_blocks_400_{block_format_version}.db", bt, seed=b"alternate2")


@pytest.fixture(scope="session")
def default_1000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(1000, f"test_blocks_1000_{block_format_version}.db", bt)


@pytest.fixture(scope="session")
def pre_genesis_empty_slots_1000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        1000, f"pre_genesis_empty_slots_1000_blocks{block_format_version}.db", bt, seed=b"alternate2", empty_sub_slots=1
    )


@pytest.fixture(scope="session")
def default_10000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(10000, f"test_blocks_10000_{block_format_version}.db", bt)


@pytest.fixture(scope="session")
def default_20000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(20000, f"test_blocks_20000_{block_format_version}.db", bt)


@pytest.fixture(scope="session")
def default_10000_blocks_compact(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        10000,
        f"test_blocks_10000_compact_{block_format_version}.db",
        bt,
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
    )


@pytest.fixture(scope="function")
def tmp_dir():
    with tempfile.TemporaryDirectory() as folder:
        yield Path(folder)


# For the below see https://stackoverflow.com/a/62563106/15133773
if os.getenv("_PYTEST_RAISE", "0") != "0":

    @pytest.hookimpl(tryfirst=True)
    def pytest_exception_interact(call):
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)
    def pytest_internalerror(excinfo):
        raise excinfo.value


@pytest_asyncio.fixture(scope="function")
async def wallet_node(self_hostname):
    async for _ in setup_node_and_wallet(test_constants, self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_nodes(db_version, self_hostname):
    async for _ in setup_two_nodes(test_constants, db_version=db_version, self_hostname=self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_nodes(db_version, self_hostname):
    async for _ in setup_n_nodes(test_constants, 3, db_version=db_version, self_hostname=self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def four_nodes(db_version, self_hostname):
    async for _ in setup_n_nodes(test_constants, 4, db_version=db_version, self_hostname=self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def five_nodes(db_version, self_hostname):
    async for _ in setup_n_nodes(test_constants, 5, db_version=db_version, self_hostname=self_hostname):
        yield _
