from __future__ import annotations

from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.full_node_rpc_api import FullNodeRpcApi
from chia.introducer.introducer import Introducer
from chia.introducer.introducer_api import IntroducerAPI
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.seeder.crawler_rpc_api import CrawlerRpcApi
from chia.server.start_service import Service
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI
from chia.wallet.wallet_rpc_api import WalletRpcApi

CrawlerService = Service[Crawler, CrawlerAPI, CrawlerRpcApi]
FullNodeService = Service[FullNode, FullNodeAPI, FullNodeRpcApi]
IntroducerService = Service[Introducer, IntroducerAPI, FullNodeRpcApi]
WalletService = Service[WalletNode, WalletNodeAPI, WalletRpcApi]
