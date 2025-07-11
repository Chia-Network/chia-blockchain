from __future__ import annotations

from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_api import DataLayerAPI
from chia.data_layer.data_layer_rpc_api import DataLayerRpcApi
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.farmer.farmer_rpc_api import FarmerRpcApi
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.full_node_rpc_api import FullNodeRpcApi
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.harvester.harvester_rpc_api import HarvesterRpcApi
from chia.introducer.introducer import Introducer
from chia.introducer.introducer_api import IntroducerAPI
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.seeder.crawler_rpc_api import CrawlerRpcApi
from chia.server.start_service import Service
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.timelord.timelord_rpc_api import TimelordRpcApi
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI
from chia.wallet.wallet_rpc_api import WalletRpcApi

CrawlerService = Service[Crawler, CrawlerAPI, CrawlerRpcApi]
DataLayerService = Service[DataLayer, DataLayerAPI, DataLayerRpcApi]
FarmerService = Service[Farmer, FarmerAPI, FarmerRpcApi]
FullNodeService = Service[FullNode, FullNodeAPI, FullNodeRpcApi]
HarvesterService = Service[Harvester, HarvesterAPI, HarvesterRpcApi]
IntroducerService = Service[Introducer, IntroducerAPI, FullNodeRpcApi]
TimelordService = Service[Timelord, TimelordAPI, TimelordRpcApi]
WalletService = Service[WalletNode, WalletNodeAPI, WalletRpcApi]
