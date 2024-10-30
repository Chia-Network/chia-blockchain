from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from logging import Logger
from typing import Callable, ClassVar, Concatenate, Optional, TypeVar, Union, get_type_hints

from typing_extensions import ParamSpec, Protocol

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.streamable import Streamable


class ApiProtocol(Protocol):
    log: Logger
    api: ClassVar[ApiMetadata]

    def ready(self) -> bool: ...


log = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S", bound=Streamable)
Self = TypeVar("Self")
metadata_attribute_name = "_chia_api_metadata"


@dataclass
class ApiRequest:
    request_type: ProtocolMessageTypes
    message_class: type[Streamable]
    method: Callable[..., object]
    peer_required: bool = False
    bytes_required: bool = False
    execute_task: bool = False
    reply_types: list[ProtocolMessageTypes] = field(default_factory=list)


def get_metadata(function: Callable[..., object]) -> Optional[ApiRequest]:
    return getattr(function, metadata_attribute_name, None)


def _set_metadata(function: Callable[..., object], metadata: ApiRequest) -> None:
    setattr(function, metadata_attribute_name, metadata)


@dataclass
class ApiMetadata:
    name_to_request: dict[str, ApiRequest] = field(default_factory=dict)

    # TODO: This hinting does not express that the returned callable *_bytes parameter
    #       corresponding to the first parameter name will be filled in by the wrapper.
    def request(
        self,
        peer_required: bool = False,
        bytes_required: bool = False,
        execute_task: bool = False,
        reply_types: Optional[list[ProtocolMessageTypes]] = None,
    ) -> Callable[[Callable[Concatenate[Self, S, P], R]], Callable[Concatenate[Self, Union[bytes, S], P], R]]:
        non_optional_reply_types: list[ProtocolMessageTypes]
        if reply_types is None:
            non_optional_reply_types = []
        else:
            non_optional_reply_types = reply_types

        def inner(f: Callable[Concatenate[Self, S, P], R]) -> Callable[Concatenate[Self, Union[bytes, S], P], R]:
            @functools.wraps(f)
            def wrapper(self: Self, original: Union[bytes, S], *args: P.args, **kwargs: P.kwargs) -> R:
                arg: S
                if isinstance(original, bytes):
                    if request.bytes_required:
                        kwargs[message_name_bytes] = original
                    arg = message_class.from_bytes(original)
                else:
                    arg = original
                    if request.bytes_required:
                        kwargs[message_name_bytes] = bytes(original)

                return f(self, arg, *args, **kwargs)

            message_name, message_class = next(
                (name, hint) for name, hint in get_type_hints(f).items() if name not in {"self", "peer", "return"}
            )
            message_name_bytes = f"{message_name}_bytes"

            request = ApiRequest(
                request_type=getattr(ProtocolMessageTypes, f.__name__),
                peer_required=peer_required,
                bytes_required=bytes_required,
                execute_task=execute_task,
                reply_types=non_optional_reply_types,
                message_class=message_class,
                method=wrapper,
            )

            if f.__name__ in self.name_to_request:
                raise Exception(f"name already registered: {f.__name__}")

            self.name_to_request[f.__name__] = request

            return wrapper

        return inner
