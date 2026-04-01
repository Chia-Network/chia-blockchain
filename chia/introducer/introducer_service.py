from __future__ import annotations

from chia.full_node.full_node_rpc_api import FullNodeRpcApi
from chia.introducer.introducer import Introducer
from chia.introducer.introducer_api import IntroducerAPI
from chia.server.start_service import Service

IntroducerService = Service[Introducer, IntroducerAPI, FullNodeRpcApi]
