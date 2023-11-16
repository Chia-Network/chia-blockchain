from __future__ import annotations

import inspect
import logging
import traceback
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Iterable,
    List,
    Optional,
    Protocol,
    Tuple,
    Union,
    cast,
    overload,
)

import aiohttp
import aiohttp.web

from chia.types.blockchain_format.coin import Coin
from chia.util.json_util import obj_to_response
from chia.wallet.conditions import Condition, ConditionValidTimes, conditions_from_json_dicts, parse_timelock_info
from chia.wallet.util.tx_config import TXConfig, TXConfigLoader

if TYPE_CHECKING:
    from chia.rpc.rpc_server import Endpoint, EndpointRequest, EndpointResult
    from chia.rpc.wallet_rpc_api import WalletRpcApi

log = logging.getLogger(__name__)

RawEndpoint = Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.Response]]


def wrap_http_handler(f: Endpoint) -> RawEndpoint:
    async def inner(request: aiohttp.web.Request) -> aiohttp.web.Response:
        request_data = await request.json()
        try:
            res_object = await f(request_data)
            if res_object is None:
                res_object = {}
            if "success" not in res_object:
                res_object["success"] = True
        except Exception as e:
            tb = traceback.format_exc()
            log.warning(f"Error while handling message: {tb}")
            if len(e.args) > 0:
                res_object = {"success": False, "error": f"{e.args[0]}", "traceback": f"{tb}"}
            else:
                res_object = {"success": False, "error": f"{e}"}

        return obj_to_response(res_object)

    return inner


class TxEndpointBase(Protocol):
    async def __call__(  # pylint: disable=E0213
        protocol_self,
        self: WalletRpcApi,
        request: EndpointRequest,
        tx_config: TXConfig,
        extra_conditions: Tuple[Condition, ...],
    ) -> EndpointResult:
        ...


# TxEndpointBase = Callable[[WalletRpcApi, EndpointRequest, TXConfig, Tuple[Condition, ...]], Awaitable[EndpointResult]]
#
class TxEndpointBaseResult(Protocol):
    async def __call__(  # pylint: disable=E0213
        protocol_self,
        self: WalletRpcApi,
        request: EndpointRequest,
    ) -> EndpointResult:
        ...


# TxEndpointBaseResult = Callable[[WalletRpcApi, EndpointRequest], Awaitable[EndpointResult]]
#
class TxEndpointHoldLock(Protocol):
    async def __call__(  # pylint: disable=E0213
        protocol_self,
        self: WalletRpcApi,
        request: EndpointRequest,
        tx_config: TXConfig,
        extra_conditions: Tuple[Condition, ...],
        hold_lock: bool = ...,
    ) -> EndpointResult:
        ...


# TxEndpointHoldLock = Callable[
#     [WalletRpcApi, EndpointRequest, TXConfig, Tuple[Condition, ...], bool], Awaitable[EndpointResult]
# ]


#
class TxEndpointHoldLockResult(Protocol):
    async def __call__(  # pylint: disable=E0213
        protocol_self,
        self: WalletRpcApi,
        request: EndpointRequest,
        hold_lock: bool = ...,
    ) -> EndpointResult:
        ...


# TxEndpointHoldLockResult = Callable[[WalletRpcApi, EndpointRequest, bool], Awaitable[EndpointResult]]

TxEndpoint = Union[TxEndpointBase, TxEndpointHoldLock]
TxEndpointResult = Union[TxEndpointBaseResult, TxEndpointHoldLockResult]


@overload
def tx_endpoint(func: TxEndpointHoldLock) -> TxEndpointHoldLockResult:
    ...


@overload
def tx_endpoint(func: TxEndpointBase) -> TxEndpointBaseResult:
    ...


def tx_endpoint(func: TxEndpoint) -> TxEndpointResult:
    async def rpc_endpoint(
        self: WalletRpcApi,
        request: EndpointRequest,
        hold_lock: bool = True,
    ) -> EndpointResult:
        assert self.service.logged_in_fingerprint is not None
        tx_config_loader: TXConfigLoader = TXConfigLoader.from_json_dict(request)

        # Some backwards compat fill-ins
        if tx_config_loader.excluded_coin_ids is None:
            tx_config_loader = tx_config_loader.override(
                excluded_coin_ids=request.get("exclude_coin_ids"),
            )
        if tx_config_loader.excluded_coin_amounts is None:
            tx_config_loader = tx_config_loader.override(
                excluded_coin_amounts=request.get("exclude_coin_amounts"),
            )
        if tx_config_loader.excluded_coin_ids is None:
            excluded_coins = cast(Optional[List[Coin]], request.get("exclude_coins", request.get("excluded_coins")))
            if excluded_coins is not None:
                tx_config_loader = tx_config_loader.override(
                    excluded_coin_ids=[Coin.from_json_dict(c).name() for c in excluded_coins],
                )

        tx_config: TXConfig = tx_config_loader.autofill(
            constants=self.service.wallet_state_manager.constants,
            config=self.service.wallet_state_manager.config,
            logged_in_fingerprint=self.service.logged_in_fingerprint,
        )

        extra_conditions: Tuple[Condition, ...] = tuple()
        if "extra_conditions" in request:
            extra_conditions = tuple(
                conditions_from_json_dicts(cast(Iterable[dict[str, Any]], request["extra_conditions"]))
            )
        extra_conditions = (*extra_conditions, *ConditionValidTimes.from_json_dict(request).to_conditions())

        valid_times: ConditionValidTimes = parse_timelock_info(extra_conditions)
        if (
            valid_times.max_secs_after_created is not None
            or valid_times.min_secs_since_created is not None
            or valid_times.max_blocks_after_created is not None
            or valid_times.min_blocks_since_created is not None
        ):
            raise ValueError("Relative timelocks are not currently supported in the RPC")

        nonlocal func
        signature = inspect.signature(func)
        if "hold_lock" in signature.parameters:
            if TYPE_CHECKING:
                func = cast(TxEndpointHoldLock, func)
            return await func(
                self, request, tx_config=tx_config, extra_conditions=extra_conditions, hold_lock=hold_lock
            )
        else:
            if TYPE_CHECKING:
                func = cast(TxEndpointBase, func)
            return await func(self, request, tx_config=tx_config, extra_conditions=extra_conditions)

    return rpc_endpoint
