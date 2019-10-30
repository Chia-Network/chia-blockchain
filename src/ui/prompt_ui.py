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
from src.server.connection import PeerConnections


log = logging.getLogger(__name__)


class FullNodeUI:
    def __init__(self, store: FullNodeStore, blockchain: Blockchain, connections: PeerConnections,
                 port: int, ssh_port: int, ssh_key_filename: str, close_cb: Callable):
        self.port = port
        self.store = store
        self.blockchain = blockchain
        self.connections = connections
        self.logs: List[logging.LogRecord] = []
        self.app: Optional[Application] = None
        self.closed = False

        def close():
            self.closed = True
            if self.app:
                self.app.exit(0)
            close_cb()
        self.close_cb = close
        kb = self.setup_keybindings()
        self.draw_initial()

        async def interact() -> None:
            self.app = Application(layout=self.layout, full_screen=True, key_bindings=kb, mouse_support=True)
            await self.app.run_async()

        asyncio.get_running_loop().create_task(asyncssh.create_server(
            lambda: PromptToolkitSSHServer(interact),
            "",
            ssh_port,
            server_host_keys=[ssh_key_filename],
        ))
        self.update_task = asyncio.get_running_loop().create_task(self.update())

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
        self.server_msg = Label(text=f'Server running on port {self.port}')
        self.syncing = TextArea(text=f'Syncing', focusable=False, height=1)
        self.current_heads = TextArea(text=f'Current heads: [0, 0, 0]', focusable=False, height=1)
        self.con_rows = []
        self.connection_rows_vsplit = Window()
        if self.app is not None:
            self.quit_button = Button('Quit', handler=self.close_cb)
        else:
            self.quit_button = Button('Quit', handler=self.close_cb)

        body = HSplit([self.server_msg, self.syncing, self.current_heads,
                       self.connection_rows_vsplit, self.quit_button],
                      height=D(), width=D())
        self.content = Frame(title="Chia Full Node", body=body)
        self.layout = Layout(VSplit([self.content], height=D(), width=D()))

    def convert_to_sync(self, async_func):
        def inner():
            asyncio.get_running_loop().create_task(async_func())
            self.layout.focus(self.quit_button)
        return inner

    async def update_draw(self):
        async with self.connections.get_lock():
            fetched_connections = await self.connections.get_connections()
        con_strs = []
        for con in fetched_connections:
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
            new_con_rows = HSplit(self.con_rows, height=D())
        else:
            new_con_rows = Window(height=D(), width=D())

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
            heads = self.blockchain.get_current_heads()
            self.current_heads.text = "Heights of heads: " + str([h.height for h in heads])
        self.content.body = HSplit([self.server_msg, self.syncing, self.current_heads,
                                    new_con_rows, self.quit_button], width=D(), height=D())

    async def update(self):
        try:
            while not self.closed:
                await self.update_draw()
                if self.app and not self.app.invalidated:
                    self.app.invalidate()
                await asyncio.sleep(1)
        except Exception as e:
            log.warn(f"Exception in UI {type(e)}: {e}")
            raise e

    async def await_closed(self):
        await self.update_task
