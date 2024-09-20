from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from ssl import SSLContext
from typing import Any, AsyncIterator, Dict, List, Optional, Type, TypeVar

import aiohttp

from chia.server.outbound_message import NodeType
from chia.server.server import ssl_context_for_client
from chia.server.ssl_context import private_ssl_ca_paths
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16

_T_RpcClient = TypeVar("_T_RpcClient", bound="RpcClient")


# It would be better to not inherit from ValueError.  This is being done to separate
# the possibility to identify these errors in new code from having to review and
# clean up existing code.
class ResponseFailureError(ValueError):
    def __init__(self, response: Dict[str, Any]):
        self.response = response
        super().__init__(f"RPC response failure: {json.dumps(response)}")


@dataclass
class RpcClient:
    """
    Client to Chia RPC, connects to a local service. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP that provides easy access
    to the full node.
    """

    url: str
    session: aiohttp.ClientSession
    ssl_context: Optional[SSLContext]
    hostname: str
    port: uint16
    closing_task: Optional[asyncio.Task] = None

    @classmethod
    async def create(
        cls: Type[_T_RpcClient],
        self_hostname: str,
        port: uint16,
        root_path: Optional[Path],
        net_config: Optional[Dict[str, Any]],
    ) -> _T_RpcClient:
        if (root_path is not None) != (net_config is not None):
            raise ValueError("Either both or neither of root_path and net_config must be provided")

        ssl_context: Optional[SSLContext]
        if root_path is None:
            scheme = "http"
            ssl_context = None
        else:
            assert root_path is not None
            assert net_config is not None
            scheme = "https"
            ca_crt_path, ca_key_path = private_ssl_ca_paths(root_path, net_config)
            crt_path = root_path / net_config["daemon_ssl"]["private_crt"]
            key_path = root_path / net_config["daemon_ssl"]["private_key"]
            ssl_context = ssl_context_for_client(ca_crt_path, ca_key_path, crt_path, key_path)

        timeout = 300
        if net_config is not None:
            timeout = net_config.get("rpc_timeout", timeout)

        self = cls(
            hostname=self_hostname,
            port=port,
            url=f"{scheme}://{self_hostname}:{str(port)}/",
            session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)),
            ssl_context=ssl_context,
        )

        return self

    @classmethod
    @asynccontextmanager
    async def create_as_context(
        cls: Type[_T_RpcClient],
        self_hostname: str,
        port: uint16,
        root_path: Optional[Path] = None,
        net_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[_T_RpcClient]:
        self = await cls.create(
            self_hostname=self_hostname,
            port=port,
            root_path=root_path,
            net_config=net_config,
        )
        try:
            yield self
        finally:
            self.close()
            await self.await_closed()

    async def fetch(self, path, request_json) -> Dict[str, Any]:
        async with self.session.post(
            self.url + path, json=request_json, ssl=self.ssl_context if self.ssl_context is not None else True
        ) as response:
            response.raise_for_status()
            res_json = await response.json()
            if not res_json["success"]:
                raise ResponseFailureError(res_json)
            return res_json

    async def get_connections(self, node_type: Optional[NodeType] = None) -> List[Dict]:
        request = {}
        if node_type is not None:
            request["node_type"] = node_type.value
        response = await self.fetch("get_connections", request)
        for connection in response["connections"]:
            connection["node_id"] = hexstr_to_bytes(connection["node_id"])
        return response["connections"]

    async def open_connection(self, host: str, port: int) -> Dict:
        return await self.fetch("open_connection", {"host": host, "port": int(port)})

    async def close_connection(self, node_id: bytes32) -> Dict:
        return await self.fetch("close_connection", {"node_id": node_id.hex()})

    async def stop_node(self) -> Dict:
        return await self.fetch("stop_node", {})

    async def healthz(self) -> Dict:
        return await self.fetch("healthz", {})

    def close(self) -> None:
        self.closing_task = asyncio.create_task(self.session.close())

    async def await_closed(self) -> None:
        if self.closing_task is not None:
            await self.closing_task
