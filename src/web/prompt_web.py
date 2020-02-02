import asyncio
import logging
import os
from typing import Callable, List, Optional, Tuple
import aiohttp

from blspy import PrivateKey, PublicKey
from yaml import safe_load

from definitions import ROOT_DIR
from src.types.full_block import FullBlock
from src.types.header_block import SmallHeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.rpc.rpc_client import RpcClient

import html
import datetime as dt
import shutil
import math
from src.consensus.constants import constants as consensus_constants

log = logging.getLogger(__name__)


async def start_ssh_server(webfilename: str, rpc_port: int):
    """
    python -m src.web.start_web foo.html -r 8555
    """
    permenantly_closed = False
    node_stop_task: Optional[asyncio.Task] = None

    rpc_client: RpcClient = await RpcClient.create(rpc_port)

    def ui_close_cb(stop_node: bool):
        nonlocal permenantly_closed, node_stop_task
        if not permenantly_closed:
            if stop_node:
                node_stop_task = asyncio.create_task(rpc_client.stop_node())
            permenantly_closed = True

    web = FullNodeUI(ui_close_cb, rpc_client, webfilename)

    async def await_all_closed():
        nonlocal web, node_stop_task
        await web.await_closed()
        if node_stop_task is not None:
            await node_stop_task
        rpc_client.close()
        await rpc_client.await_closed()

    return await_all_closed, ui_close_cb


class FullNodeUI:
    """
    Full node UI instance. Displays node state, blocks, and connections. Calls parent_close_cb
    when the full node is closed. Uses the RPC client to fetch data from a full node and to display relevant
    information. The UI is updated periodically.
    """

    def __init__(self, parent_close_cb: Callable, rpc_client: RpcClient, webfilename: str):
        self.rpc_client = rpc_client
        self.data_initialized = False
        self.block = None
        self.closed: bool = False
        self.num_top_block_pools: int = 10
        self.top_winners: List[Tuple[uint64, bytes32]] = []
        self.our_winners: List[Tuple[uint64, bytes32]] = []
        self.prev_route: str = "home/"
        self.route: str = "home/"
        self.focused: bool = False

        self.pool_pks: List[PublicKey] = []
        key_config_filename = os.path.join(ROOT_DIR, "config", "keys.yaml")
        if os.path.isfile(key_config_filename):
            config = safe_load(open(key_config_filename, "r"))

            self.pool_pks = [
                PrivateKey.from_bytes(bytes.fromhex(ce)).get_public_key()
                for ce in config["pool_sks"]
            ]

        self.num_blocks: int = 10
        self.introducer_ts = 0
        self.topfarmers = {}
        self.topfarmerindex = 0

        self.closed = False

        self.update_data_task = asyncio.get_running_loop().create_task(
            self.update_data()
        )

        self.constants = consensus_constants
        self.webfilename = webfilename

    async def get_latest_blocks(
        self, heads: List[SmallHeaderBlock]
    ) -> List[SmallHeaderBlock]:
        added_blocks: List[SmallHeaderBlock] = []
        while len(heads) > 0:
            heads = sorted(heads, key=lambda b: b.height, reverse=True)
            max_block = heads[0]
            if max_block not in added_blocks:
                added_blocks.append(max_block)
            heads.remove(max_block)
            prev: Optional[SmallHeaderBlock] = await self.rpc_client.get_header(
                max_block.prev_header_hash
            )
            if prev is not None:
                heads.append(prev)
            if len(added_blocks) >= self.num_blocks and max_block.height <= self.topfarmerindex:
                break
        return added_blocks

    async def dump_status(self):
        log.info(f"dump_status *****************")

        total_iters = 0
        lcatimestamp = 0

        try:
            os.remove('index.html')
        except OSError:
            pass

        st = open('index.html', 'w')

        print("<html><head><link rel=\"stylesheet\" href=\"styles.css\">", file=st)
        print("<title>Chia Blockchain Status</title></head><body><main>", file=st)

        if self.sync_mode:
            if self.max_height >= 0:
                print(f"<p>Chia Testnet Blockchain: Syncing up to {str(self.max_height)}</p>", file=st)
            else:
                print(f"<p>Chia Testnet Blockchain: Syncing</p>", file=st)
        else:
            print("<p>Chia Testnet Blockchain: Currently synced</p>", file=st)

        total_iters = self.lca_block.challenge.total_iters

        print(f"<ul style=\"list-style-type:none;\">", file=st)
        for i, b in enumerate(self.latest_blocks):
            print(
                 f"<li><a href=\"#{str(b.header_hash)}\">{b.height}: {b.header_hash}"
                 f" {'LCA' if b.header_hash == self.lca_block.header_hash else ''}"
                 f" {'TIP' if b.header_hash in [h.header_hash for h in self.tips] else ''}</a>", file=st)
            block: Optional[FullBlock] = await self.rpc_client.get_block(b.header_hash)

            print(f"<ul style=\"list-style-type:none;\" class=\"expando\" id=\"{str(b.header_hash)}\">", file=st)
            print(f"<li><pre>{html.escape(str(block))}</pre></li>", file=st)
            print(f"</ul></li>", file=st)
            if i >= self.num_blocks:
                break
        print("</ul>", file=st)

        for b in reversed(self.latest_blocks):
            block: Optional[FullBlock] = await self.rpc_client.get_block(b.header_hash)
            if((block.header_block.challenge.height <= self.lca_block.height) and
                    (self.topfarmerindex < block.header_block.challenge.height)):
                self.topfarmerindex = block.header_block.challenge.height
                farmer = block.body.fees_target_info.puzzle_hash.hex()
                self.topfarmers[farmer] = self.topfarmers.get(farmer, 0) + 1
                #log.info(f"farmer {farmer} {self.topfarmers[farmer]}")

        block = await self.rpc_client.get_block(self.lca_block.header_hash)
        lcatimestamp = block.header_block.header.data.timestamp
        print(f"<p>Current LCA timestamp (UTC): {dt.datetime.utcfromtimestamp(lcatimestamp)}</p>", file=st)
        print(f"<p>Current difficulty: {self.difficulty}</p>", file=st)

        epochs = math.ceil(
            (self.lca_block.height-self.constants["DIFFICULTY_DELAY"]) / self.constants["DIFFICULTY_EPOCH"]
        )
        ipsupdate = epochs * self.constants["DIFFICULTY_EPOCH"] + self.constants["DIFFICULTY_DELAY"]
        print(f"<p>Current VDF iterations per second: {self.ips} (update at {ipsupdate})</p>", file=st)

        print(f"<p>Total iterations since genesis: {total_iters}</p>", file=st)

        sorted_x = sorted(self.topfarmers.items(), key=lambda kv: kv[1], reverse=True)
        print("<p>Top Farmers</p><ul style=\"list-style-type:none;\">", file=st)
        for field, value in sorted_x:
            print(f'<li>{field} : {value}</li>', file=st)
        print('</ul></main></body></html>', file=st)

        st.close()
        shutil.copy('index.html', self.webfilename)

    async def update_data(self):
        self.data_initialized = False

        try:
            while not self.closed:
                try:
                    blockchain_state = await self.rpc_client.get_blockchain_state()
                    self.lca_block = blockchain_state["lca"]
                    self.tips = blockchain_state["tips"]
                    self.difficulty = blockchain_state["difficulty"]
                    self.ips = blockchain_state["ips"]
                    self.sync_mode = blockchain_state["sync_mode"]
                    if self.sync_mode:
                        max_block = await self.rpc_client.get_heaviest_block_seen()
                        self.max_height = max_block.height

                    self.latest_blocks = await self.get_latest_blocks(self.tips)

                    self.data_initialized = True

                    await self.dump_status()

                    await asyncio.sleep(5*60)
                except (
                    aiohttp.client_exceptions.ClientConnectorError,
                    aiohttp.client_exceptions.ServerConnectionError,
                ) as e:
                    log.warning(f"Could not connect to full node. Is it running? {e}")
                    await asyncio.sleep(5)
        except Exception as e:
            log.error(f"Exception in UI update_data {type(e)}: {e}")
            raise e

    async def await_closed(self):
        await self.update_data_task
