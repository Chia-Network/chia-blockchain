import asyncio
from typing import List, Callable
import tkinter as tk
from src.store.full_node_store import FullNodeStore
from src.blockchain import Blockchain


class FullNodeUI(tk.Tk):
    def __init__(self, loop, store: FullNodeStore, blockchain: Blockchain, close_cb: Callable, interval: float = 1):
        super().__init__()
        self.loop = loop
        self.store = store
        self.blockchain = blockchain

        def full_close():
            for task in self.tasks:
                task.cancel()
            self.destroy()
            close_cb()
        self.close_cb = full_close
        self.protocol("WM_DELETE_WINDOW", self.close_cb)

        self.create_widgets()
        self.tasks: List[asyncio.Task] = []
        self.tasks.append(loop.create_task(self.store_fetcher(1)))
        self.tasks.append(loop.create_task(self.updater(interval)))

    def create_widgets(self):
        # canvas = tk.Canvas(self, height=600, width=600)
        self.frame = tk.Frame(height=500, width=500, relief=tk.SUNKEN)
        self.frame.pack(fill=tk.X, padx=5, pady=5)
        self.frame.pack_propagate(0)

        # canvas.pack()
        self.sync_mode = tk.Label(self.frame)
        self.sync_mode["text"] = "Syncing"
        self.sync_mode.pack(side="top")
        self.current_heads = tk.Label(self.frame)
        self.current_heads["text"] = str([0, 0, 0])
        self.current_heads.pack(side="top")

        # self.hi_there = tk.Button(self.frame, height=1, width=20)
        # self.hi_there["text"] = "Hello World (click me)"
        # self.hi_there["command"] = self.say_hi
        # self.hi_there.pack(side="top")

        self.quit = tk.Button(self.frame, text="QUIT", fg="red",
                              command=self.close_cb)
        self.quit.pack(side="bottom")

    async def store_fetcher(self, interval):
        while True:
            print("Fetching")
            async with (await self.store.get_lock()):
                if (await self.store.get_sync_mode()):
                    potential_heads = await self.store.get_potential_heads()
                    fbs = [await self.store.get_potential_heads_full_block(ph) for ph in potential_heads]
                    max_height = max([b.height for b in fbs])
                    self.sync_mode["text"] = f"Syncing up to {str(max_height)}"
                else:
                    self.sync_mode["text"] = "Not syncing"
                heads = self.blockchain.get_current_heads()
                self.current_heads["text"] = str([h.height for h in heads])

            await asyncio.sleep(interval)

    async def updater(self, interval):
        while True:
            print("Updating")
            self.update()
            await asyncio.sleep(interval)


def start_ui(store: FullNodeStore, blockchain: Blockchain, close_cb: Callable):
    loop = asyncio.get_event_loop()
    FullNodeUI(loop, store, blockchain, close_cb)
