from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable
from dataclasses import dataclass, field
from logging import Logger
from typing import Callable, ClassVar, Optional, TypeVar, Union, final, get_type_hints

from typing_extensions import Concatenate, ParamSpec, Protocol

from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.streamable import Streamable


class ApiProtocol(Protocol):
    log: Logger
    metadata: ClassVar[ApiMetadata]

    def ready(self) -> bool: ...


log = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R", bound=Awaitable[Optional[Message]])
S = TypeVar("S", bound=Streamable)
Self = TypeVar("Self")
api_attribute_name = "_chia_api"


@dataclass
class ApiRequest:
    request_type: ProtocolMessageTypes
    message_class: type[Streamable]
    method: Callable[..., Awaitable[Optional[Message]]]
    peer_required: bool = False
    bytes_required: bool = False
    execute_task: bool = False
    reply_types: list[ProtocolMessageTypes] = field(default_factory=list)


@final
@dataclass
class ApiMetadata:
    message_type_to_request: dict[ProtocolMessageTypes, ApiRequest] = field(default_factory=dict)

    @classmethod
    def copy(cls, original: ApiMetadata) -> ApiMetadata:
        return cls(message_type_to_request=dict(original.message_type_to_request))

    @classmethod
    def from_bound_method(cls, method: Callable[..., Awaitable[Optional[Message]]]) -> ApiRequest:
        self: ApiMetadata = getattr(method, api_attribute_name)
        message_type = ProtocolMessageTypes[method.__name__]
        return self.message_type_to_request[message_type]

    # TODO: This hinting does not express that the returned callable *_bytes parameter
    #       corresponding to the first parameter name will be filled in by the wrapper.
    def request(
        self,
        peer_required: bool = False,
        bytes_required: bool = False,
        execute_task: bool = False,
        reply_types: Optional[list[ProtocolMessageTypes]] = None,
        request_type: Optional[ProtocolMessageTypes] = None,
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

            setattr(wrapper, api_attribute_name, self)
            message_name, message_class = next(
                (name, hint) for name, hint in get_type_hints(f).items() if name not in {"self", "peer", "return"}
            )
            message_name_bytes = f"{message_name}_bytes"

            nonlocal request_type
            if request_type is None:
                request_type = ProtocolMessageTypes[f.__name__]

            request = ApiRequest(
                request_type=request_type,
                peer_required=peer_required,
                bytes_required=bytes_required,
                execute_task=execute_task,
                reply_types=non_optional_reply_types,
                message_class=message_class,
                method=wrapper,
            )

            if request_type in self.message_type_to_request:
                raise Exception(f"request type already registered: {request_type}")

            self.message_type_to_request[request_type] = request

            return wrapper

        return inner
