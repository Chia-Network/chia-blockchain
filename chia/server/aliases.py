from __future__ import annotations

from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.full_node_rpc_api import FullNodeRpcApi
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.seeder.crawler_rpc_api import CrawlerRpcApi
from chia.server.start_service import Service

CrawlerService = Service[Crawler, CrawlerAPI, CrawlerRpcApi]
FullNodeService = Service[FullNode, FullNodeAPI, FullNodeRpcApi]
