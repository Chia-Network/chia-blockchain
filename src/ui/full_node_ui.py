import asyncio
from typing import List, Callable
import tkinter as tk
from tkinter import ttk, scrolledtext  # type: ignore
import logging
from src.store.full_node_store import FullNodeStore
from src.blockchain import Blockchain
from src.server.connection import PeerConnections
from prompt_toolkit.contrib.ssh import PromptToolkitSSHServer
import asyncssh


log = logging.getLogger(__name__)


class FullNodeUI(tk.Tk):
    def __init__(self, loop, store: FullNodeStore, blockchain: Blockchain,
                 connections: PeerConnections, port: int, close_cb_param: Callable, interval: float = 1/60):
        super().__init__()
        self.loop = loop
        self.store = store
        self.connections = connections
        self.blockchain = blockchain

        def full_close():
            for task in self.tasks:
                task.cancel()
            self.destroy()
            close_cb_param()

        self.close_cb = full_close
        self.protocol("WM_DELETE_WINDOW", self.close_cb)

        self.create_widgets(port)
        self.tasks: List[asyncio.Task] = []
        self.tasks.append(loop.create_task(self.store_fetcher(1)))
        self.tasks.append(loop.create_task(self.updater(interval)))

    def create_widgets(self, port: int):
        self.geometry("600x500")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand="yes")

        self.frame = ttk.Frame(self.notebook)
        self.frame.pack()
        self.notebook.add(self.frame, text="General")

        self.logs = ttk.Frame(self.notebook)
        self.logs.pack()
        self.logs_data = scrolledtext.ScrolledText(self.logs)
        self.logs_data.pack(fill='both', expand=True, padx=8, pady=8)
        self.logs_data.insert("insert", f"This is a line \n Maybe add some more \nAnd some more")

        self.notebook.add(self.logs, text="Logs")

        # canvas.pack()
        self.port = ttk.Label(self.frame)
        self.port["text"] = f"Server running on port {port}"
        self.port.pack(side="top")

        self.sync_mode = ttk.Label(self.frame)
        self.sync_mode["text"] = "Syncing"
        self.sync_mode.pack(side="top")

        self.current_heads = ttk.Label(self.frame)
        self.current_heads["text"] = "Heights of heads: " + str([0, 0, 0])
        self.current_heads.pack(side="top")

        self.peers_title = ttk.Label(self.frame)
        self.peers_title["text"] = "Peer connections"
        self.peers_title.pack()
        self.peers = ttk.Frame(self.frame)
        self.peers.pack()
        self.quit_button = ttk.Button(self.frame, text="Quit",
                                      command=self.close_cb)
        self.quit_button.pack(side="bottom")

    def convert_to_sync(self, async_func):
        def inner():
            self.loop.create_task(async_func())
        return inner

    async def store_fetcher(self, interval):
        try:
            while True:
                async with self.connections.get_lock():
                    fetched_connections = await self.connections.get_connections()
                children = self.peers.winfo_children()
                con_labels = [child.winfo_children()[0]["text"] for child in children]
                for con in fetched_connections:
                    con_str = f"{con.connection_type} {con.get_peername()} {con.node_id.hex()[:10]}..."
                    if con_str not in con_labels:
                        row = ttk.Frame(self.peers)
                        con_label = ttk.Label(row)
                        con_label["text"] = con_str
                        con_label.pack(side="left")
                        disconnect_button = ttk.Button(row, text="Disconnect",
                                                       command=self.convert_to_sync(con.close))
                        disconnect_button.pack(side="left")
                        row.pack(side="top")
                    else:
                        index = con_labels.index(con_str)
                        del con_labels[index]
                        del children[index]
                for child in children:
                    child.destroy()

                # print(f"{len(await self.connections.get_connections())} connections")
                async with (await self.store.get_lock()):
                    if (await self.store.get_sync_mode()):
                        potential_heads = await self.store.get_potential_heads()
                        fbs = [await self.store.get_potential_heads_full_block(ph) for ph in potential_heads]
                        if len(fbs) > 0:
                            max_height = max([b.height for b in fbs])
                            self.sync_mode["text"] = f"Syncing up to {str(max_height)}"
                        else:
                            self.sync_mode["text"] = f"Syncing"

                    else:
                        self.sync_mode["text"] = "Not syncing"
                    heads = self.blockchain.get_current_heads()
                    self.current_heads["text"] = "Heights of heads: " + str([h.height for h in heads])

                await asyncio.sleep(interval)
        except Exception as e:
            log.error(f"Exception in UI: {type(e)} {e}")
            raise e

    async def updater(self, interval):
        while True:
            self.update()
            await asyncio.sleep(interval)


def start_ui(store: FullNodeStore, blockchain: Blockchain, connections: PeerConnections,
             port: int, close_cb: Callable):
    loop = asyncio.get_running_loop()
    ui = FullNodeUI(loop, store, blockchain, connections, port, close_cb)
    ui.wm_title('Chia Network Full Node')
