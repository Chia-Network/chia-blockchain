from typing import Callable, Dict, List

from chia.seeder.crawler import Crawler
from chia.util.ws_message import WsRpcMessage


class CrawlerRpcApi:
    def __init__(self, crawler: Crawler):
        self.service = crawler
        self.service_name = "chia_crawler"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_peer_counts": self.get_peer_counts,
        }

    async def _state_changed(self, change: str, change_data: Dict) -> List[WsRpcMessage]:
        return []

    async def get_peer_counts(self, request: Dict) -> Dict:
        peer_counts = {
            "total_last_5_days": "",
            "reliable_nodes": "",
            "ipv4_last_5_days": "",
            "ipv6_last_5_days": "",
            "versions": [],
        }
        return peer_counts
