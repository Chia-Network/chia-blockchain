from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Type, TypeVar, get_type_hints

import aiohttp
from typing_extensions import TypedDict, dataclass_transform

from chia.types.blockchain_format.coin import Coin
from chia.util.json_util import obj_to_response
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import Condition, ConditionValidTimes, conditions_from_json_dicts, parse_timelock_info
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import TXConfig, TXConfigLoader

log = logging.getLogger(__name__)

RpcEndpoint = Callable[..., Coroutine[Any, Any, Dict[str, Any]]]
MarshallableRpcEndpoint = Callable[..., Coroutine[Any, Any, Streamable]]


class RequestType(TypedDict):
    pass


_T_Streamable = TypeVar("_T_Streamable", bound="Streamable")


@dataclass_transform()
def get_streamable_from_request_type(cls: Type[RequestType]) -> Type[_T_Streamable]:
    return streamable(
        dataclass(frozen=True)(type("_" + cls.__name__, (Streamable,), {"__annotations__": cls.__annotations__}))
    )


def marshall(func: MarshallableRpcEndpoint) -> RpcEndpoint:
    hints = get_type_hints(func)
    request_class: Type[RequestType] = hints["request"]

    async def rpc_endpoint(self, request: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
        response_obj: Streamable = await func(
            self,
            request_class(
                get_streamable_from_request_type(request_class).from_json_dict(request).__dict__  # type: ignore
            ),
            *args,
            **kwargs,
        )
        return response_obj.to_json_dict()

    return rpc_endpoint


def wrap_http_handler(f) -> Callable:
    async def inner(request) -> aiohttp.web.Response:
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


def tx_endpoint(push: bool = False, merge_spends: bool = True) -> Callable[[RpcEndpoint], RpcEndpoint]:
    def _inner(func: RpcEndpoint) -> RpcEndpoint:
        async def rpc_endpoint(self, request: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
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
                excluded_coins: Optional[List[Coin]] = request.get("exclude_coins", request.get("excluded_coins"))
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
                extra_conditions = tuple(conditions_from_json_dicts(request["extra_conditions"]))
            extra_conditions = (*extra_conditions, *ConditionValidTimes.from_json_dict(request).to_conditions())

            valid_times: ConditionValidTimes = parse_timelock_info(extra_conditions)
            if (
                valid_times.max_secs_after_created is not None
                or valid_times.min_secs_since_created is not None
                or valid_times.max_blocks_after_created is not None
                or valid_times.min_blocks_since_created is not None
            ):
                raise ValueError("Relative timelocks are not currently supported in the RPC")

            response: Dict[str, Any] = await func(
                self,
                request,
                *args,
                tx_config=tx_config,
                extra_conditions=extra_conditions,
                **kwargs,
            )

            if func.__name__ == "create_new_wallet" and "transactions" not in response:
                # unfortunately, this API isn't solely a tx endpoint
                return response

            tx_records: List[TransactionRecord] = [
                TransactionRecord.from_json_dict_convenience(tx) for tx in response["transactions"]
            ]

            if request.get("push", push):
                await self.service.wallet_state_manager.add_pending_transactions(tx_records, merge_spends=merge_spends)

            return response

        return rpc_endpoint

    return _inner
