import asyncio
import logging
import collections
import os
from typing import Callable, List, Optional, Tuple
from yaml import safe_load
from blspy import PrivateKey, PublicKey

import asyncssh

from prompt_toolkit import Application
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.key_binding.bindings.focus import (
    focus_next,
    focus_previous,
)
from prompt_toolkit.contrib.ssh import PromptToolkitSSHServer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, Frame, Label, SearchToolbar, TextArea
from src.blockchain import Blockchain
from src.database import FullNodeStore
from src.server.connection import NodeType, PeerConnections
from src.server.server import ChiaServer
from src.consensus.block_rewards import calculate_block_reward
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.util.ints import uint16, uint64
from definitions import ROOT_DIR

log = logging.getLogger(__name__)


async def start_ssh_server(
    store: FullNodeStore,
    blockchain: Blockchain,
    server: ChiaServer,
    port: int,
    ssh_port: int,
    ssh_key_filename: str,
    close_cb: Callable,
):
    """
    Starts an SSH Server that creates FullNodeUI instances whenever someone connects to the port.
    returns a coroutine that can be awaited, which returns when all ui instances have been closed.
    """
    uis = []  # type: ignore
    permenantly_closed = False
    ssh_server = None

    def ui_close_cb():
        nonlocal uis, permenantly_closed
        if not permenantly_closed:
            log.info("Closing all connected UIs")
            for ui in uis:
                ui.close()
            if ssh_server is not None:
                ssh_server.close()
            close_cb()
            permenantly_closed = True

    async def await_all_closed():
        nonlocal uis
        while len(uis) > 0:
            ui = uis[0]
            await ui.await_closed()
            uis = uis[1:]
        await ssh_server.wait_closed()

    async def interact():
        nonlocal uis, permenantly_closed
        if permenantly_closed:
            return
        ui = FullNodeUI(store, blockchain, server, port, ui_close_cb)
        assert ui.app
        uis.append(ui)
        try:
            await ui.app.run_async()
        except ConnectionError:
            log.info("Connection error in ssh UI, exiting.")
            ui.close()
            raise

    ssh_server = await asyncssh.create_server(
        lambda: PromptToolkitSSHServer(interact),
        "",
        ssh_port,
        server_host_keys=[ssh_key_filename],
        reuse_address=True,
    )

    return await_all_closed, ui_close_cb


class FullNodeUI:
    """
    Full node UI instance. Displays node state, blocks, and connections. Calls parent_close_cb
    when the full node is closed. Uses store, blockchain, and connections, to display relevant
    information. The UI is updated periodically.
    """

    def __init__(
        self,
        store: FullNodeStore,
        blockchain: Blockchain,
        server: ChiaServer,
        port: int,
        parent_close_cb: Callable,
    ):
        self.port: int = port
        self.store: FullNodeStore = store
        self.blockchain: Blockchain = blockchain
        self.node_server: ChiaServer = server
        self.connections: PeerConnections = server.global_connections
        self.logs: List[logging.LogRecord] = []
        self.app: Optional[Application] = None
        self.closed: bool = False
        self.num_blocks: int = 10
        self.num_top_block_pools: int = 5
        self.top_winners: List[Tuple[uint64, bytes32]] = []
        self.our_winners: List[Tuple[uint64, bytes32]] = []
        self.prev_route: str = "home/"
        self.route: str = "home/"
        self.focused: bool = False
        self.parent_close_cb = parent_close_cb
        self.kb = self.setup_keybindings()
        self.style = Style([("error", "#ff0044")])
        self.pool_pks: List[PublicKey] = []
        key_config_filename = os.path.join(ROOT_DIR, "config", "keys.yaml")
        if os.path.isfile(key_config_filename):
            config = safe_load(open(key_config_filename, "r"))

            self.pool_pks = [
                PrivateKey.from_bytes(bytes.fromhex(ce)).get_public_key()
                for ce in config["pool_sks"]
            ]

        self.draw_initial()
        self.app = Application(
            style=self.style,
            layout=self.layout,
            full_screen=True,
            key_bindings=self.kb,
            mouse_support=True,
        )

        self.closed = False
        self.update_ui_task = asyncio.get_running_loop().create_task(self.update_ui())
        self.update_data_task = asyncio.get_running_loop().create_task(
            self.update_data()
        )

    def close(self):
        # Closes this instance of the UI
        if not self.closed:
            self.closed = True
            self.route = "home/"
            if self.app:
                self.app.exit(0)

    def stop(self):
        # Closes this instance of the UI, and call parent close, which closes
        # all other instances, and shuts down the full node.
        self.close()
        self.parent_close_cb()

    def setup_keybindings(self) -> KeyBindings:
        kb = KeyBindings()
        kb.add("tab")(focus_next)
        kb.add("s-tab")(focus_previous)
        kb.add("down")(focus_next)
        kb.add("up")(focus_previous)
        kb.add("right")(focus_next)
        kb.add("left")(focus_previous)

        @kb.add("c-c")
        def exit_(event):
            self.close()

        return kb

    def draw_initial(self):
        search_field = SearchToolbar()
        self.empty_row = TextArea(focusable=False, height=1)

        # home/
        self.loading_msg = Label(text=f"Initializing UI....")
        self.server_msg = Label(text=f"Server running on port {self.port}.")
        self.syncing = TextArea(focusable=False, height=1)
        self.current_heads_label = TextArea(focusable=False, height=1)
        self.lca_label = TextArea(focusable=False, height=1)
        self.difficulty_label = TextArea(focusable=False, height=1)
        self.ips_label = TextArea(focusable=False, height=1)
        self.total_iters_label = TextArea(focusable=False, height=2)
        self.con_rows = []
        self.displayed_cons = []
        self.latest_blocks: List[HeaderBlock] = []
        self.connections_msg = Label(text=f"Connections")
        self.connection_rows_vsplit = Window()
        self.add_connection_msg = Label(text=f"Add a connection ip:port")
        self.add_connection_field = TextArea(
            height=1,
            prompt=">>> ",
            style="class:input-field",
            multiline=False,
            wrap_lines=False,
            search_field=search_field,
        )
        self.add_connection_field.accept_handler = self.async_to_sync(
            self.add_connection
        )
        self.latest_blocks_msg = Label(text=f"Latest blocks")
        self.latest_blocks_labels = [
            Button(text="block") for _ in range(self.num_blocks)
        ]

        self.search_block_msg = Label(text=f"Search block by hash")
        self.search_block_field = TextArea(
            height=1,
            prompt=">>> ",
            style="class:input-field",
            multiline=False,
            wrap_lines=False,
            search_field=search_field,
        )
        self.search_block_field.accept_handler = self.async_to_sync(self.search_block)

        self.top_block_pools_msg = Label(text=f"Top block pools")
        self.top_block_pools_labels = [
            Label(text="Top block pool") for _ in range(self.num_top_block_pools)
        ]
        self.our_pools_msg = Label(text=f"Our pool winnings")
        self.our_pools_labels = [
            Label(text="Our winnings") for _ in range(len(self.pool_pks))
        ]

        self.close_ui_button = Button("Close UI", handler=self.close)
        self.quit_button = Button("Stop node and close UI", handler=self.stop)
        self.error_msg = Label(style="class:error", text=f"")

        # block/
        self.block_msg = Label(text=f"Block")
        self.block_label = TextArea(focusable=True, scrollbar=True, focus_on_click=True)
        self.back_button = Button(
            text="Back", handler=self.change_route_handler("home/")
        )
        self.challenge_msg = Label(text=f"Block Header")
        self.challenge = TextArea(focusable=False)

        body = HSplit([self.loading_msg, self.server_msg], height=D(), width=D())
        self.content = Frame(title="Chia Full Node", body=body)
        self.layout = Layout(VSplit([self.content], height=D(), width=D()))

    def change_route_handler(self, route):
        def change_route():
            self.prev_route = self.route
            self.route = route
            self.focused = False
            self.error_msg.text = ""

        return change_route

    def async_to_sync(self, coroutine):
        def inner(buff):
            asyncio.get_running_loop().create_task(coroutine(buff.text))

        return inner

    async def search_block(self, text: str):
        try:
            block = await self.store.get_block(bytes.fromhex(text))
        except ValueError:
            self.error_msg.text = "Enter a valid hex block hash"
            return
        if block is not None:
            self.change_route_handler(f"block/{text}")()
        else:
            self.error_msg.text = "Block not found"

    async def add_connection(self, text: str):
        if ":" not in text:
            self.error_msg.text = (
                "Enter a valid IP and port in the following format: 10.5.4.3:8000"
            )
            return
        else:
            ip, port = ":".join(text.split(":")[:-1]), text.split(":")[-1]
        target_node: PeerInfo = PeerInfo(ip, uint16(int(port)))
        log.error(f"Want to connect to {ip}, {port}")
        if not (await self.node_server.start_client(target_node, None)):
            self.error_msg.text = f"Failed to connect to {ip}:{port}"

    async def get_latest_blocks(self, heads: List[HeaderBlock]) -> List[HeaderBlock]:
        added_blocks: List[HeaderBlock] = []
        while len(added_blocks) < self.num_blocks and len(heads) > 0:
            heads = sorted(heads, key=lambda b: b.height, reverse=True)
            max_block = heads[0]
            if max_block not in added_blocks:
                added_blocks.append(max_block)
            heads.remove(max_block)
            prev: Optional[HeaderBlock] = self.blockchain.header_blocks.get(
                max_block.prev_header_hash, None
            )
            if prev is not None:
                heads.append(prev)
        return added_blocks

    async def draw_home(self):
        connections = [c for c in self.connections.get_connections()]
        if collections.Counter(connections) != collections.Counter(self.displayed_cons):
            new_con_rows = []
            for con in connections:
                con_str = f"{NodeType(con.connection_type).name} {con.get_peername()} {con.node_id.hex()[:10]}..."
                con_label = Label(text=con_str)

                def disconnect(c):
                    def inner():
                        self.connections.close(c)
                        self.layout.focus(self.quit_button)

                    return inner

                disconnect_button = Button("Disconnect", handler=disconnect(con))
                row = VSplit([con_label, disconnect_button])
                new_con_rows.append(row)
            self.displayed_cons = connections
            self.con_rows = new_con_rows
            if len(self.con_rows) > 0:
                self.layout.focus(self.con_rows[0])
            else:
                self.layout.focus(self.quit_button)

        if len(self.con_rows):
            new_con_rows = HSplit(self.con_rows)
        else:
            new_con_rows = Window(width=D(), height=0)

        if await self.store.get_sync_mode():
            max_height = -1
            for _, block in await self.store.get_potential_tips_tuples():
                if block.height > max_height:
                    max_height = block.height

            if max_height >= 0:
                self.syncing.text = f"Syncing up to {max_height}"
            else:
                self.syncing.text = f"Syncing"
        else:
            self.syncing.text = "Not syncing"
        heads: List[HeaderBlock] = self.blockchain.get_current_tips()

        lca_block: HeaderBlock = self.blockchain.lca_block
        if lca_block.height > 0:
            difficulty = self.blockchain.get_next_difficulty(lca_block.prev_header_hash)
            ips = self.blockchain.get_next_ips(lca_block.prev_header_hash)
        else:
            difficulty = self.blockchain.get_next_difficulty(lca_block.header_hash)
            ips = self.blockchain.get_next_ips(lca_block.header_hash)
        total_iters = lca_block.challenge.total_iters

        new_block_labels = []
        for i, b in enumerate(self.latest_blocks):
            self.latest_blocks_labels[i].text = (
                f"{b.height}:{b.header_hash}"
                f" {'LCA' if b.header_hash == lca_block.header_hash else ''}"
                f" {'TIP' if b.header_hash in [h.header_hash for h in heads] else ''}"
            )
            self.latest_blocks_labels[i].handler = self.change_route_handler(
                f"block/{b.header_hash}"
            )
            new_block_labels.append(self.latest_blocks_labels[i])

        top_block_pools_labels = self.top_block_pools_labels
        if len(self.top_winners) > 0:
            new_top_block_pools_labels = []
            for i, (winnings, pk) in enumerate(self.top_winners):
                self.top_block_pools_labels[
                    i
                ].text = f"Public key {pk.hex()}: {winnings/1000000000000} chias."
                new_top_block_pools_labels.append(self.top_block_pools_labels[i])
            top_block_pools_labels = new_top_block_pools_labels

        our_pools_labels = self.our_pools_labels
        if len(self.our_winners) > 0:
            new_our_pools_labels = []
            for i, (winnings, pk) in enumerate(self.our_winners):
                self.our_pools_labels[
                    i
                ].text = f"Public key {pk.hex()}: {winnings/(1000000000000)} chias."
                new_our_pools_labels.append(self.our_pools_labels[i])
            our_pools_labels = new_our_pools_labels

        self.lca_label.text = f"Current least common ancestor {lca_block.header_hash} height {lca_block.height}"
        self.current_heads_label.text = "Heights of tips: " + str(
            [h.height for h in heads]
        )
        self.difficulty_label.text = f"Current difficuty: {difficulty}"
        self.ips_label.text = f"Current VDF iterations per second: {ips}"
        self.total_iters_label.text = f"Total iterations since genesis: {total_iters}"

        try:
            if not self.focused:
                self.layout.focus(self.close_ui_button)
                self.focused = True
        except ValueError:  # Not yet in layout
            pass
        return HSplit(
            [
                self.server_msg,
                self.syncing,
                self.lca_label,
                self.current_heads_label,
                self.difficulty_label,
                self.ips_label,
                self.total_iters_label,
                Window(height=1, char="-", style="class:line"),
                self.connections_msg,
                new_con_rows,
                Window(height=1, char="-", style="class:line"),
                self.add_connection_msg,
                self.add_connection_field,
                Window(height=1, char="-", style="class:line"),
                self.latest_blocks_msg,
                *new_block_labels,
                Window(height=1, char="-", style="class:line"),
                self.search_block_msg,
                self.search_block_field,
                Window(height=1, char="-", style="class:line"),
                self.top_block_pools_msg,
                *top_block_pools_labels,
                Window(height=1, char="-", style="class:line"),
                self.our_pools_msg,
                *our_pools_labels,
                Window(height=1, char="-", style="class:line"),
                self.close_ui_button,
                self.quit_button,
                self.error_msg,
            ],
            width=D(),
            height=D(),
        )

    async def draw_block(self):
        block_hash: str = self.route.split("block/")[1]
        async with self.store.lock:
            block: Optional[FullBlock] = await self.store.get_block(
                bytes32(bytes.fromhex(block_hash))
            )
        if block is not None:
            self.block_msg.text = f"Block {str(block.header_hash)}"
            if self.block_label.text != str(block):
                self.block_label.text = str(block)
        else:
            self.block_label.text = f"Block hash {block_hash} not found"
        try:
            if not self.focused:
                self.layout.focus(self.back_button)
                self.focused = True
        except ValueError:  # Not yet in layout
            pass
        return HSplit(
            [self.block_msg, self.block_label, self.back_button], width=D(), height=D()
        )

    async def update_ui(self):
        try:
            while not self.closed:
                if self.route.startswith("home/"):
                    self.content.body = await self.draw_home()
                elif self.route.startswith("block/"):
                    self.content.body = await self.draw_block()

                if self.app and not self.app.invalidated:
                    self.app.invalidate()
                await asyncio.sleep(1.5)
        except Exception as e:
            log.warn(f"Exception in UI update_ui {type(e)}: {e}")
            raise e

    async def update_data(self):
        try:
            while not self.closed:
                heads: List[HeaderBlock] = self.blockchain.get_current_tips()
                self.latest_blocks = await self.get_latest_blocks(heads)

                header_block = heads[0]
                coin_balances = {
                    bytes(
                        header_block.proof_of_space.pool_pubkey
                    ): calculate_block_reward(header_block.height)
                }
                while header_block.height != 0:
                    header_block = self.blockchain.header_blocks[
                        header_block.prev_header_hash
                    ]
                    pool_pk = bytes(header_block.proof_of_space.pool_pubkey)
                    if pool_pk not in coin_balances:
                        coin_balances[pool_pk] = 0
                    coin_balances[pool_pk] += calculate_block_reward(
                        header_block.height
                    )
                self.top_winners = sorted(
                    [(rewards, key) for key, rewards in coin_balances.items()],
                    reverse=True,
                )[: self.num_top_block_pools]

                self.our_winners = [
                    (coin_balances[bytes(pk)], bytes(pk))
                    if bytes(pk) in coin_balances
                    else (0, bytes(pk))
                    for pk in self.pool_pks
                ]
                await asyncio.sleep(7.5)
        except Exception as e:
            log.warn(f"Exception in UI update_data {type(e)}: {e}")
            raise e

    async def await_closed(self):
        await self.update_ui_task
        await self.update_data_task
