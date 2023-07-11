from __future__ import annotations

import logging
import traceback
from typing import Any, Callable, Coroutine, Dict, List, Optional

import aiohttp

from chia.types.blockchain_format.coin import Coin
from chia.util.json_util import obj_to_response
from chia.wallet.util.tx_config import TXConfig, TXConfigLoader

log = logging.getLogger(__name__)


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
                res_object = {"success": False, "error": f"{e.args[0]}"}
            else:
                res_object = {"success": False, "error": f"{e}"}

        return obj_to_response(res_object)

    return inner


def tx_endpoint(
    func: Callable[..., Coroutine[Any, Any, Dict[str, Any]]]
) -> Callable[..., Coroutine[Any, Any, Dict[str, Any]]]:
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
        return await func(self, request, *args, tx_config=tx_config, **kwargs)

    return rpc_endpoint
