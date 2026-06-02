from __future__ import annotations

from typing import Literal

from aiohttp import ClientWebSocketResponse


def decoded_client_websocket(ws: ClientWebSocketResponse[bool]) -> ClientWebSocketResponse[Literal[True]]:
    # aiohttp 3.14's precise ws_connect() overloads are only available to mypy on Python 3.11+.
    # Callers use this after passing decode_text=True so Python 3.10 type checking sees the same contract.
    return ws  # type: ignore[return-value]
