from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from chia.cmds.cmds_util import get_any_service_client
from chia.cmds.units import units
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint64

async def init_cmd(
    rpc_port: int,
    directory: str,
    withdrawal_timelock: int,
    payment_clawback: int,
    rekey_cancel: int,
    rekey_timelock: int,
    slow_penalty: int,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.init(directory, withdrawal_timelock, payment_clawback, rekey_cancel, rekey_timelock, slow_penalty)
            print(res)

async def derive_cmd(
    rpc_port: int,
    configuration: str,
    db_path: str,
    pubkeys: str,
    initial_lock_level: int,
    minimum_pks: int,
    validate_against: str,
    maximum_lock_level: int,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.derive(configuration, db_path, pubkeys, initial_lock_level, minimum_pks, validate_against, maximum_lock_level)
            print(res)


async def launch_cmd(
    rpc_port: int,
    configuration: str,
    db_path: str,
    wallet_rpc_port: int,
    fingerprint: int,
    node_rpc_port: int,
    fee: int,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.launch(configuration, db_path, wallet_rpc_port, fingerprint, node_rpc_port, fee)
            print(res)


async def sync_cmd(
    rpc_port: int,
    configuration: Optional[str],
    db_path: str,
    node_rpc_port: Optional[int],
    show: bool,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.sync(configuration, db_path, node_rpc_port, show)
            print(res)


async def show_cmd(
    rpc_port: int,
    db_path: str,
    config: bool,
    derivation: bool,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.show(db_path, config, derivation)
            print(res)

async def address_cmd(
    rpc_port: int,
    db_path: str,
    prefix: str,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.address(db_path, prefix)
            print(res)


async def push_cmd(
    rpc_port: int,
    spend_bundle: str,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    node_rpc_port: Optional[int],
    fee: int,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.push(spend_bundle, wallet_rpc_port, fingerprint, node_rpc_port, fee)
            print(res)


async def payments_cmd(
    rpc_port: int,
    db_path: str,
    pubkeys: str,
    amount: int,
    recipient_address: str,
    absorb_available_payments: bool,
    maximum_extra_cost: Optional[int],
    amount_threshold: int,
    filename: Optional[str],
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.payments(db_path, pubkeys, amount, recipient_address, absorb_available_payments, maximum_extra_cost, amount_threshold, filename)
            print(res)


async def hsmgen_cmd(
    rpc_port: int,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.hsmgen()
            print(res)

 
async def hsmpk_cmd(
    rpc_port: int,
    secretkey: str,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.hsmpk(secretkey)
            print(res)


async def hsms_cmd(
    rpc_port: int,
    message:str,
    secretkey: str,
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.hsms(message, secretkey)
            print(res)


async def hsmmerge_cmd(
    rpc_port: int,
    bundle: str,
    sigs: str
) -> None:
    async with get_any_service_client("custody", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.hsmmerge(bundle, sigs)
            print(res)


