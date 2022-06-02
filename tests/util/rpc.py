from chia.rpc.rpc_client import RpcClient
from chia.rpc.rpc_server import RpcApiProtocol


async def validate_get_routes(client: RpcClient, api: RpcApiProtocol):
    routes_client = (await client.fetch("get_routes", {}))["routes"]
    assert len(routes_client) > 0
    routes_api = list(api.get_routes().keys())
    # TODO: avoid duplication of RpcServer.get_routes()
    routes_server = [
        "/get_connections",
        "/open_connection",
        "/close_connection",
        "/stop_node",
        "/get_routes",
        "/healthz",
    ]
    assert len(routes_api) > 0

    all_server_routes = {*routes_api, *routes_server}
    all_client_routes = {*routes_client}
    only_server = sorted(all_server_routes - all_client_routes)
    only_client = sorted(all_client_routes - all_server_routes)

    assert [only_server, only_client] == [[], []]
