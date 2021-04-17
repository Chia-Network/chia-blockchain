import asyncio
import logging
import time
from typing import Optional

from chia.server.server import ChiaServer
from chia.server.introducer_peers import VettedPeer
from chia.util.ints import uint64


class Introducer:
    def __init__(self, max_peers_to_send: int, recent_peer_threshold: int):
        self.max_peers_to_send = max_peers_to_send
        self.recent_peer_threshold = recent_peer_threshold
        self._shut_down = False
        self.server: Optional[ChiaServer] = None
        self.log = logging.getLogger(__name__)

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

                peer: VettedPeer
                for peer in raw_peers:
                    if self._shut_down:
                        return

                    now = time.time()

                    # if it was too long ago we checked this peer, check it
                    # again
                    if peer.vetted > 0 and now > peer.vetted_timestamp + 3600:
                        peer.vetted = 0

                    if peer.vetted > 0:
                        continue

                    # don't re-vet peers too frequently
                    if now < peer.last_attempt + 500:
                        continue

                    try:
                        peer.last_attempt = uint64(time.time())

                        self.log.info(f"Vetting peer {peer.host} {peer.port}")
                        r, w = await asyncio.wait_for(
                            asyncio.open_connection(peer.host, int(peer.port)),
                            timeout=3,
                        )
                        w.close()
                    except Exception as e:
                        self.log.warning(f"Could not vet {peer}, removing. {type(e)}{str(e)}")
                        peer.vetted = min(peer.vetted - 1, -1)

                        # if we have failed 6 times in a row, remove the peer
                        if peer.vetted < -6:
                            self.server.introducer_peers.remove(peer)
                        continue

                    self.log.info(f"Have vetted {peer} successfully!")
                    peer.vetted_timestamp = uint64(time.time())
                    peer.vetted = max(peer.vetted + 1, 1)
            except Exception as e:
                self.log.error(e)
