from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional, TextIO

import click
from aiohttp import ClientResponseError

from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16

services: List[str] = ["crawler", "farmer", "full_node", "harvester", "timelord", "wallet", "data_layer"]


async def call_endpoint(service: str, endpoint: str, request: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    from chia.rpc.rpc_client import RpcClient

    port: uint16
    if service == "crawler":
        # crawler config is inside the seeder config
        port = uint16(config["seeder"][service]["rpc_port"])
    else:
        port = uint16(config[service]["rpc_port"])

    try:
        client = await RpcClient.create(config["self_hostname"], port, DEFAULT_ROOT_PATH, config)
    except Exception as e:
        raise Exception(f"Failed to create RPC client {service}: {e}")
    result: Dict[str, Any]
    try:
        result = await client.fetch(endpoint, request)
    except ClientResponseError as e:
        if e.code == 404:
            raise Exception(f"Invalid endpoint for {service}: {endpoint}")
        raise
    except Exception as e:
        raise Exception(f"Request failed: {e}")
    finally:
        client.close()
        await client.await_closed()
    return result


def print_result(json_dict: Dict[str, Any]) -> None:
    print(json.dumps(json_dict, indent=4, sort_keys=True))


def get_routes(service: str, config: Dict[str, Any]) -> Dict[str, Any]:
    return asyncio.run(call_endpoint(service, "get_routes", {}, config))


@click.group("rpc", help="RPC Client")
def rpc_cmd() -> None:
    pass


@rpc_cmd.command("endpoints", help="Print all endpoints of a service")
@click.argument("service", type=click.Choice(services))
def endpoints_cmd(service: str) -> None:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    try:
        routes = get_routes(service, config)
        for route in routes["routes"]:
            print(route[1:])
    except Exception as e:
        print(e)


@rpc_cmd.command("status", help="Print the status of all available RPC services")
def status_cmd() -> None:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")

    def print_row(c0: str, c1: str) -> None:
        c0 = "{0:<12}".format(f"{c0}")
        c1 = "{0:<9}".format(f"{c1}")
        print(f"{c0} | {c1}")

    print_row("SERVICE", "STATUS")
    print_row("------------", "---------")
    for service in services:
        status = "ACTIVE"
        try:
            if not get_routes(service, config)["success"]:
                raise Exception()
        except Exception:
            status = "INACTIVE"
        print_row(service, status)


def create_commands() -> None:
    for service in services:

        @rpc_cmd.command(
            service,
            short_help=f"RPC client for the {service} RPC API",
            help=(
                f"Call ENDPOINT (RPC endpoint as as string) of the {service} "
                "RPC API with REQUEST (must be a JSON string) as request data."
            ),
        )
        @click.argument("endpoint", type=str)
        @click.argument("request", type=str, required=False)
        @click.option(
            "-j",
            "--json-file",
            help="Optionally instead of REQUEST you can provide a json file containing the request data",
            type=click.File("r"),
            default=None,
        )
        def rpc_client_cmd(
            endpoint: str, request: Optional[str], json_file: Optional[TextIO], service: str = service
        ) -> None:
            config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
            if request is not None and json_file is not None:
                sys.exit(
                    "Can only use one request source: REQUEST argument OR -j/--json-file option. See the help with -h"
                )

            request_json: Dict[str, Any] = {}
            if json_file is not None:
                try:
                    request_json = json.load(json_file)
                except Exception as e:
                    sys.exit(f"Invalid JSON file: {e}")
            if request is not None:
                try:
                    request_json = json.loads(request)
                except Exception as e:
                    sys.exit(f"Invalid REQUEST JSON: {e}")

            try:
                if endpoint[0] == "/":
                    endpoint = endpoint[1:]
                print_result(asyncio.run(call_endpoint(service, endpoint, request_json, config)))
            except Exception as e:
                sys.exit(str(e))


create_commands()
