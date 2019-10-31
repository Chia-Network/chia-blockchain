from typing import Callable, List, Optional
import asyncio
import logging
import asyncssh
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.contrib.ssh import PromptToolkitSSHServer
from prompt_toolkit.key_binding.bindings.focus import (
    focus_next,
    focus_previous,
)
from prompt_toolkit import Application
from prompt_toolkit.layout.containers import VSplit, HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.widgets import (
    Frame,
    Label,
    TextArea,
    Button
)
from src.store.full_node_store import FullNodeStore
from src.blockchain import Blockchain
from src.types.trunk_block import TrunkBlock
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.server.connection import PeerConnections


log = logging.getLogger(__name__)


class FullNodeUI:
    def __init__(self, store: FullNodeStore, blockchain: Blockchain, connections: PeerConnections,
                 port: int, ssh_port: int, ssh_key_filename: str, close_cb: Callable):
        self.port: int = port
        self.store: FullNodeStore = store
        self.blockchain: Blockchain = blockchain
        self.connections: PeerConnections = connections
        self.logs: List[logging.LogRecord] = []
        self.app: Optional[Application] = None
        self.closed: bool = False
        self.num_blocks: int = 10
        self.prev_route: str = "home/"
        self.route: str = "home/"
        self.focused: bool = False

        def close():
            log.info("Closing the UI")
            self.closed = True
            self.route = "home/"
            if self.app:
                self.app.exit(0)

        def stop():
            close()
            close_cb()

        self.stop_cb = stop
        self.close_cb = close
        kb = self.setup_keybindings()
        self.draw_initial()

        async def interact() -> None:
            self.app = Application(layout=self.layout, full_screen=True, key_bindings=kb, mouse_support=True)
            self.closed = False
            self.update_task = asyncio.get_running_loop().create_task(self.update())
            await self.app.run_async()

        asyncio.get_running_loop().create_task(asyncssh.create_server(
            lambda: PromptToolkitSSHServer(interact),
            "",
            ssh_port,
            server_host_keys=[ssh_key_filename],
        ))

    def setup_keybindings(self) -> KeyBindings:
        kb = KeyBindings()
        kb.add('tab')(focus_next)
        kb.add('s-tab')(focus_previous)
        kb.add('down')(focus_next)
        kb.add('up')(focus_previous)
        kb.add('right')(focus_next)
        kb.add('left')(focus_previous)

        @kb.add('c-c')
        def exit_(event):
            self.close_cb()
        return kb

    def draw_initial(self):
        self.empty_row = TextArea(focusable=False, height=1)

        self.loading_msg = Label(text=f'Initializing UI....')
        self.server_msg = Label(text=f'Server running on port {self.port}.')
        self.syncing = TextArea(focusable=False, height=1)
        self.current_heads_label = TextArea(focusable=False, height=1)
        self.lca_label = TextArea(focusable=False, height=1)
        self.difficulty_label = TextArea(focusable=False, height=1)
        self.ips_label = TextArea(focusable=False, height=1)
        self.total_iters_label = TextArea(focusable=False, height=2)
        self.con_rows = []
        self.connections_msg = Label(text=f'Connections')
        self.connection_rows_vsplit = Window()

        self.latest_blocks_msg = Label(text=f'Latest blocks')
        self.latest_blocks_labels = [Button(text="block") for _ in range(self.num_blocks)]
        self.quit_button = Button('Stop node and close UI', handler=self.stop_cb)
        self.close_ui_button = Button('Close UI', handler=self.close_cb)

        body = HSplit([self.loading_msg, self.server_msg],
                      height=D(), width=D())
        self.content = Frame(title="Chia Full Node", body=body)
        self.layout = Layout(VSplit([self.content], height=D(), width=D()))

        self.block_label = TextArea(focusable=True, scrollbar=True)
        self.back_button = Button(text="Back", handler=self.change_route_handler("home/"))

    def change_route_handler(self, route):
        def change_route():
            self.prev_route = self.route
            self.route = route
            self.focused = False
        return change_route

    def convert_to_sync(self, async_func):
        def inner():
            asyncio.get_running_loop().create_task(async_func())
            self.layout.focus(self.quit_button)
        return inner

    async def get_latest_blocks(self, heads: List[TrunkBlock]) -> List[TrunkBlock]:
        added_blocks: List[TrunkBlock] = []
        # index =
        while len(added_blocks) < self.num_blocks and len(heads) > 0:
            heads = sorted(heads, key=lambda b: b.height, reverse=True)
            max_block = heads[0]
            if max_block not in added_blocks:
                added_blocks.append(max_block)
            heads.remove(max_block)
            async with await self.store.get_lock():
                prev: Optional[FullBlock] = await self.store.get_block(max_block.prev_header_hash)
                if prev is not None:
                    heads.append(prev.trunk_block)
        return added_blocks

    async def draw_home(self):
        con_strs = []
        for con in self.connections.get_connections():
            con_str = f"{con.connection_type} {con.get_peername()} {con.node_id.hex()[:10]}..."
            con_strs.append(con_str)
            labels = [row.children[0].content.text() for row in self.con_rows]
            if con_str not in labels:
                con_label = Label(text=con_str)
                disconnect_button = Button("Disconnect", handler=self.convert_to_sync(con.close))
                row = VSplit([con_label, disconnect_button])
                self.con_rows.append(row)

        new_con_rows = [row for row in self.con_rows if row.children[0].content.text() in con_strs]
        if new_con_rows != self.con_rows:
            self.con_rows = new_con_rows
            if len(self.con_rows) > 0:
                self.layout.focus(self.con_rows[0])
            else:
                self.layout.focus(self.quit_button)

        if len(self.con_rows):
            new_con_rows = HSplit(self.con_rows)
        else:
            new_con_rows = Window(width=D(), height=0)

        async with (await self.store.get_lock()):
            if (await self.store.get_sync_mode()):
                potential_heads = await self.store.get_potential_heads()
                fbs = [await self.store.get_potential_heads_full_block(ph) for ph in potential_heads]
                if len(fbs) > 0:
                    max_height = max([b.height for b in fbs])
                    self.syncing.text = f"Syncing up to {str(max_height)}"
                else:
                    self.syncing.text = f"Syncing"

            else:
                self.syncing.text = "Not syncing"
            heads: List[TrunkBlock] = self.blockchain.get_current_heads()
            lca_block: FullBlock = self.blockchain.lca_block
            if lca_block.height > 0:
                difficulty = await self.blockchain.get_next_difficulty(lca_block.prev_header_hash)
                ips = await self.blockchain.get_next_ips(lca_block.prev_header_hash)
            else:
                difficulty = await self.blockchain.get_next_difficulty(lca_block.header_hash)
                ips = await self.blockchain.get_next_ips(lca_block.header_hash)
        total_iters = lca_block.trunk_block.challenge.total_iters
        latest_blocks: List[TrunkBlock] = await self.get_latest_blocks(heads)
        if len(latest_blocks) > 0:
            new_labels = []
            for i, b in enumerate(latest_blocks):
                self.latest_blocks_labels[i].text = (
                    f"{b.height}:{b.header_hash}"
                    f" {'LCA' if b.header_hash == lca_block.header_hash else ''}"
                    f" {'HEAD' if b.header_hash in [h.header_hash for h in heads] else ''}")
                self.latest_blocks_labels[i].handler = self.change_route_handler(f"block/{b.header_hash}")
                new_labels.append(self.latest_blocks_labels[i])

        self.lca_label.text = f"Current least common ancestor {lca_block.header_hash} height {lca_block.height}"
        self.current_heads_label.text = "Heights of heads: " + str([h.height for h in heads])
        self.difficulty_label.text = f"Current difficuty: {difficulty}"
        self.ips_label.text = f"Current VDF iterations per second: {ips}"
        self.total_iters_label.text = f"Total iterations since genesis: {total_iters}"
        return HSplit([self.server_msg, self.syncing, self.lca_label, self.current_heads_label,
                       self.difficulty_label, self.ips_label, self.total_iters_label, self.connections_msg,
                       new_con_rows, self.empty_row, self.latest_blocks_msg, *new_labels,
                       self.close_ui_button, self.quit_button], width=D(), height=D())

    async def draw_block(self):
        block_hash: str = self.route.split("block/")[1]
        async with await self.store.get_lock():
            block: Optional[FullBlock] = await self.store.get_block(bytes32(bytes.fromhex(block_hash)))
        if block is not None:
            if self.block_label.text != str(block):
                self.block_label.text = str(block)
        else:
            self.block_label.text = f"Block hash {block_hash} not found"
        return HSplit([self.block_label, self.back_button], width=D(), height=D())

    async def update(self):
        try:
            while not self.closed:
                if self.route.startswith("home/"):
                    self.content.body = await self.draw_home()
                elif self.route.startswith("block/"):
                    self.content.body = await self.draw_block()

                if self.prev_route != self.route and not self.focused:
                    self.layout.focus_next()
                    self.focused = True

                if self.app and not self.app.invalidated:
                    self.app.invalidate()
                await asyncio.sleep(2)
        except Exception as e:
            log.warn(f"Exception in UI {type(e)}: {e}")
            raise e

    async def await_closed(self):
        await self.update_task
