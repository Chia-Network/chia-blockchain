from typing import Any, Callable, Dict, List, Optional

from chia.seeder.crawler import Crawler
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class CrawlerRpcApi:
    def __init__(self, crawler: Crawler):
        self.service = crawler
        self.service_name = "chia_crawler"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_peer_counts": self.get_peer_counts,
        }

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> List[WsRpcMessage]:
        payloads = []

        if change_data is None:
            change_data = {}

        if change == "crawl_batch_completed" or change == "loaded_initial_peers":
            payloads.append(
                create_payload_dict(
                    change,
                    change_data,
                    self.service_name,
                    "metrics"
                )
            )

        return payloads

    async def get_peer_counts(self, request: Dict) -> Dict:
        peer_counts = {
            "total_last_5_days": 0,
            "reliable_nodes": 0,
            "ipv4_last_5_days": 0,
            "ipv6_last_5_days": 0,
            "versions": [],
        }
        return peer_counts
