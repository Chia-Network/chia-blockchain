from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol, Tuple, TypeVar

from chia.rpc.rpc_server import RpcApiProtocol, RpcServer, RpcServiceProtocol
from chia.server.api_protocol import ApiProtocol
from chia.server.server import ChiaServer
from chia.server.start_service import Service

T_Node = TypeVar("T_Node", bound=RpcServiceProtocol)
T_RpcApi = TypeVar("T_RpcApi", bound=RpcApiProtocol)
T_PeerApi = TypeVar("T_PeerApi", bound=ApiProtocol)


@dataclass
class ServiceEnvironment(Protocol[T_Node, T_RpcApi, T_PeerApi]):
    service: Service[T_Node, T_PeerApi, T_RpcApi]

    __match_args__: ClassVar[Tuple[str, ...]] = ()

    @property
    def node(self) -> T_Node: ...

    @property
    def rpc_api(self) -> T_RpcApi: ...

    @property
    def rpc_server(self) -> RpcServer[T_RpcApi]: ...

    @property
    def peer_api(self) -> T_PeerApi: ...

    @property
    def peer_server(self) -> ChiaServer: ...
