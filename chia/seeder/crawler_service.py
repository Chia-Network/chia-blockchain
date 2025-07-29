from __future__ import annotations

from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.seeder.crawler_rpc_api import CrawlerRpcApi
from chia.server.start_service import Service

CrawlerService = Service[Crawler, CrawlerAPI, CrawlerRpcApi]
