from __future__ import annotations

import cProfile
import logging
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, List, Optional, cast

import aiosqlite
import zstd

from chia._tests.util.constants import test_constants as TEST_CONSTANTS
from chia.cmds.init_funcs import chia_init
from chia.consensus.constants import replace_str_to_bytes
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.full_node.full_node import FullNode
from chia.server.outbound_message import Message, NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import ConnectionCallback, WSChiaConnection
from chia.simulator.block_tools import make_unfinished_block
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config
from chia.util.ints import uint16


class ExitOnError(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.exit_with_failure = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno != logging.ERROR:
            return
        self.exit_with_failure = True


@contextmanager
def enable_profiler(profile: bool, counter: int) -> Iterator[None]:
    if not profile:
        yield
        return

    with cProfile.Profile() as pr:
        receive_start_time = time.monotonic()
        yield

    if time.monotonic() - receive_start_time > 5:
        pr.create_stats()
        pr.dump_stats(f"slow-batch-{counter:05d}.profile")


class FakeServer:
    async def send_to_all(
        self, messages: List[Message], node_type: NodeType, exclude: Optional[bytes32] = None
    ) -> None:
        pass

    async def send_to_all_if(
        self,
        messages: List[Message],
        node_type: NodeType,
        predicate: Callable[[WSChiaConnection], bool],
        exclude: Optional[bytes32] = None,
    ) -> None:
        pass

    def set_received_message_callback(self, callback: ConnectionCallback) -> None:
        pass

    async def get_peer_info(self) -> Optional[PeerInfo]:
        return None

    def get_connections(
        self, node_type: Optional[NodeType] = None, *, outbound: Optional[bool] = False
    ) -> List[WSChiaConnection]:
        return []

    def is_duplicate_or_self_connection(self, target_node: PeerInfo) -> bool:
        return False

    async def start_client(
        self,
        target_node: PeerInfo,
        on_connect: Optional[ConnectionCallback] = None,
        auth: bool = False,
        is_feeler: bool = False,
    ) -> bool:
        return False


class FakePeer:
    def get_peer_logging(self) -> PeerInfo:
        return PeerInfo("0.0.0.0", uint16(0))

    def __init__(self) -> None:
        self.peer_node_id = bytes([0] * 32)

    async def get_peer_info(self) -> Optional[PeerInfo]:
        return None


async def run_sync_test(
    file: Path,
    db_version: int,
    profile: bool,
    single_thread: bool,
    test_constants: bool,
    keep_up: bool,
    db_sync: str,
    node_profiler: bool,
    start_at_checkpoint: Optional[str],
) -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.WARNING)
    handler = logging.FileHandler("test-full-sync.log")
    handler.setFormatter(
        logging.Formatter(
            "%(levelname)-8s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    check_log = ExitOnError()
    logger.addHandler(check_log)

    with tempfile.TemporaryDirectory() as root_dir:
        root_path = Path(root_dir, "root")
        if start_at_checkpoint is not None:
            shutil.copytree(start_at_checkpoint, root_path)

        chia_init(root_path, should_check_keys=False, v1_db=(db_version == 1))
        config = load_config(root_path, "config.yaml")

        if test_constants:
            constants = TEST_CONSTANTS
        else:
            overrides = config["network_overrides"]["constants"][config["selected_network"]]
            constants = replace_str_to_bytes(DEFAULT_CONSTANTS, **overrides)
        if single_thread:
            config["full_node"]["single_threaded"] = True
        config["full_node"]["db_sync"] = db_sync
        config["full_node"]["enable_profiler"] = node_profiler
        full_node = await FullNode.create(
            config["full_node"],
            root_path=root_path,
            consensus_constants=constants,
        )

        full_node.set_server(cast(ChiaServer, FakeServer()))
        async with full_node.manage():
            peak = full_node.blockchain.get_peak()
            if peak is not None:
                height = int(peak.height)
            else:
                height = 0

            peer: WSChiaConnection = cast(WSChiaConnection, FakePeer())

            print()
            counter = 0
            monotonic = height
            prev_hash = None
            async with aiosqlite.connect(file) as in_db:
                await in_db.execute("pragma query_only")
                rows = await in_db.execute(
                    "SELECT header_hash, height, block FROM full_blocks "
                    "WHERE height >= ? AND in_main_chain=1 ORDER BY height",
                    (height,),
                )

                block_batch = []

                start_time = time.monotonic()
                logger.warning(f"starting test {start_time}")
                worst_batch_height = None
                worst_batch_time_per_block = None
                peer_info = peer.get_peer_logging()
                async for r in rows:
                    batch_start_time = time.monotonic()
                    with enable_profiler(profile, height):
                        block = FullBlock.from_bytes(zstd.decompress(r[2]))
                        block_batch.append(block)

                        assert block.height == monotonic
                        monotonic += 1
                        assert prev_hash is None or block.prev_header_hash == prev_hash
                        prev_hash = block.header_hash

                        if len(block_batch) < 32:
                            continue

                        if keep_up:
                            for b in block_batch:
                                await full_node.add_unfinished_block(make_unfinished_block(b, constants), peer)
                                await full_node.add_block(b, None, full_node._bls_cache)
                        else:
                            block_record = await full_node.blockchain.get_block_record_from_db(
                                block_batch[0].prev_header_hash
                            )
                            ssi, diff = get_next_sub_slot_iters_and_difficulty(
                                full_node.constants, True, block_record, full_node.blockchain
                            )
                            success, summary, _, _, _, _ = await full_node.add_block_batch(
                                block_batch, peer_info, None, current_ssi=ssi, current_difficulty=diff
                            )
                            end_height = block_batch[-1].height
                            full_node.blockchain.clean_block_record(end_height - full_node.constants.BLOCKS_CACHE_SIZE)

                            if not success:
                                raise RuntimeError("failed to ingest block batch")

                            assert summary is not None

                        time_per_block = (time.monotonic() - batch_start_time) / len(block_batch)
                        if not worst_batch_height or worst_batch_time_per_block > time_per_block:
                            worst_batch_height = height
                            worst_batch_time_per_block = time_per_block

                    counter += len(block_batch)
                    height += len(block_batch)
                    print(
                        f"\rheight {height} {time_per_block:0.2f} s/block   ",
                        end="",
                    )
                    block_batch = []
                    if check_log.exit_with_failure:
                        raise RuntimeError("error printed to log. exiting")

                    if counter >= 100000:
                        counter = 0
                        print()
                end_time = time.monotonic()
                logger.warning(f"test completed at {end_time}")
                logger.warning(f"duration: {end_time - start_time:0.2f} s")
                logger.warning(f"worst time-per-block: {worst_batch_time_per_block:0.2f} s")
                logger.warning(f"worst height: {worst_batch_height}")
                logger.warning(f"end-height: {height}")
            if node_profiler:
                (root_path / "profile-node").rename("./profile-node")
