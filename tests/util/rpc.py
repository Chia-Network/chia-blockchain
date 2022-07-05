async def validate_get_routes(client, api):
    routes_client = (await client.fetch("get_routes", {}))["routes"]
    assert len(routes_client) > 0
    routes_api = list(api.get_routes().keys())
    routes_server = [
        "/get_connections",
        "/open_connection",
        "/close_connection",
        "/stop_node",
        "/get_routes",
    ]
    assert len(routes_api) > 0
    for route in routes_api + routes_server:
        assert route in routes_client
