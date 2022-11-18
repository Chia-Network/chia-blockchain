from __future__ import annotations

import ipaddress
from typing import Any, Dict, List, Optional

from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.seeder.crawler import Crawler
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class CrawlerRpcApi:
    def __init__(self, crawler: Crawler):
        self.service = crawler
        self.service_name = "chia_crawler"

    def get_routes(self) -> Dict[str, Endpoint]:
        return {
            "/get_peer_counts": self.get_peer_counts,
            "/get_ips_after_timestamp": self.get_ips_after_timestamp,
        }

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> List[WsRpcMessage]:
        payloads = []

        if change_data is None:
            change_data = await self.get_peer_counts({})

        if change in ("crawl_batch_completed", "loaded_initial_peers"):
            payloads.append(create_payload_dict(change, change_data, self.service_name, "metrics"))

        return payloads

    async def get_peer_counts(self, _request: Dict) -> EndpointResult:
        ipv6_addresses_count = 0
        for host in self.service.best_timestamp_per_peer.keys():
            try:
                ipaddress.IPv6Address(host)
                ipv6_addresses_count += 1
            except ipaddress.AddressValueError:
                continue

        reliable_peers = 0
        if self.service.crawl_store is not None:
            reliable_peers = self.service.crawl_store.get_reliable_peers()

        data = {
            "peer_counts": {
                "total_last_5_days": len(self.service.best_timestamp_per_peer),
                "reliable_nodes": reliable_peers,
                "ipv4_last_5_days": len(self.service.best_timestamp_per_peer) - ipv6_addresses_count,
                "ipv6_last_5_days": ipv6_addresses_count,
                "versions": self.service.versions,
            }
        }
        return data

    async def get_ips_after_timestamp(self, _request: Dict) -> EndpointResult:
        after = _request.get("after", None)
        if after is None:
            raise ValueError("`after` is required and must be a unix timestamp")

        offset = _request.get("offset", 0)
        limit = _request.get("limit", 10000)

        matched_ips: List[str] = []
        for ip, timestamp in self.service.best_timestamp_per_peer.items():
            if timestamp > after:
                matched_ips.append(ip)

        matched_ips.sort()

        return {
            "ips": matched_ips[offset : (offset + limit)],
            "total": len(matched_ips),
        }
