import asyncio
import logging
import time
from typing import Callable, Dict, Optional

from chia.server.server import ChiaServer
from chia.types.blockchain_format.sized_bytes import bytes32


class Introducer:
    def __init__(self, max_peers_to_send: int, recent_peer_threshold: int):
        self.vetted: Dict[bytes32, bool] = {}
        self.vetted_timestamps: Dict[bytes32, int] = {}
        self.max_peers_to_send = max_peers_to_send
        self.recent_peer_threshold = recent_peer_threshold
        self._shut_down = False
        self.server: Optional[ChiaServer] = None
        self.log = logging.getLogger(__name__)
        self.state_changed_callback: Optional[Callable] = None

    async def _start(self):
        self._vetting_task = asyncio.create_task(self._vetting_loop())

    def _close(self):
        self._shut_down = True
        self._vetting_task.cancel()

    async def _await_closed(self):
        pass
        # await self._vetting_task

    def set_server(self, server: ChiaServer):
        self.server = server

    async def _vetting_loop(self):
        while True:
            if self._shut_down:
                return
            try:
                for i in range(60):
                    if self._shut_down:
                        return
                    await asyncio.sleep(1)
                self.log.info("Vetting random peers.")
                if self.server.introducer_peers is None:
                    continue
                raw_peers = self.server.introducer_peers.get_peers(100, True, 3 * self.recent_peer_threshold)

                if len(raw_peers) == 0:
                    continue

                for peer in raw_peers:
                    if self._shut_down:
                        return
                    if peer.get_hash() in self.vetted_timestamps:
                        if time.time() > self.vetted_timestamps[peer.get_hash()] + 3600:
                            if peer.get_hash() in self.vetted:
                                self.vetted[peer.get_hash()] = False
                    if peer.get_hash() not in self.vetted or not self.vetted[peer.get_hash()]:
                        try:
                            self.log.info(f"Vetting peer {peer.host} {peer.port}")
                            r, w = await asyncio.wait_for(
                                asyncio.open_connection(peer.host, int(peer.port)),
                                timeout=3,
                            )
                            w.close()
                        except Exception as e:
                            self.log.warning(f"Could not vet {peer}. {type(e)}{str(e)}")
                            self.vetted[peer.get_hash()] = False
                            continue

                        self.log.info(f"Have vetted {peer} successfully!")
                        self.vetted[peer.get_hash()] = True
                        self.vetted_timestamps[peer.get_hash()] = int(time.time())
            except Exception as e:
                self.log.error(e)
