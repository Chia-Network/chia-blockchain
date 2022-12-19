from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Callable, ClassVar, List, Optional, Type, TypeVar, Union, get_type_hints

from typing_extensions import Concatenate, ParamSpec, Protocol

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType
from chia.util.streamable import Streamable

log = logging.getLogger(__name__)


class _NodeProtocol(Protocol):
    node_type: ClassVar[NodeType]


P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S", bound=Streamable)
_T_NodeProtocol = TypeVar("_T_NodeProtocol", bound=_NodeProtocol)
Self = TypeVar("Self")


incomplete_metadata_attribute_name = "_chia_incomplete_api_metadata"
metadata_attribute_name = "_chia_api_metadata"


@dataclass
class ApiMetadata:
    request_type: ProtocolMessageTypes
    message_class: Type[Streamable]
    node_type: NodeType
    peer_required: bool = False
    bytes_required: bool = False
    execute_task: bool = False
    reply_types: List[ProtocolMessageTypes] = field(default_factory=list)


def get_metadata(function: Callable[..., object]) -> Optional[ApiMetadata]:
    return getattr(function, metadata_attribute_name, None)


def _set_metadata(function: Callable[..., object], metadata: ApiMetadata) -> None:
    setattr(function, metadata_attribute_name, metadata)


def _set_incomplete_metadata(function: Callable[..., object], metadata: ApiMetadata) -> None:
    setattr(function, incomplete_metadata_attribute_name, metadata)


# TODO: This hinting does not express that the returned callable *_bytes parameter
#       corresponding to the first parameter name will be filled in by the wrapper.
def api_request(
    peer_required: bool = False,
    bytes_required: bool = False,
    execute_task: bool = False,
    reply_types: Optional[List[ProtocolMessageTypes]] = None,
) -> Callable[[Callable[Concatenate[Self, S, P], R]], Callable[Concatenate[Self, Union[bytes, S], P], R]]:
    non_optional_reply_types: List[ProtocolMessageTypes]
    if reply_types is None:
        non_optional_reply_types = []
    else:
        non_optional_reply_types = reply_types

    def inner(f: Callable[Concatenate[Self, S, P], R]) -> Callable[Concatenate[Self, Union[bytes, S], P], R]:
        def wrapper(self: Self, original: Union[bytes, S], *args: P.args, **kwargs: P.kwargs) -> R:
            arg: S
            if isinstance(original, bytes):
                if metadata.bytes_required:
                    kwargs[message_name_bytes] = original
                arg = message_class.from_bytes(original)
            else:
                arg = original
                if metadata.bytes_required:
                    kwargs[message_name_bytes] = bytes(original)

            return f(self, arg, *args, **kwargs)

        message_name, message_class = next(
            (name, hint) for name, hint in get_type_hints(f).items() if name not in {"self", "peer", "return"}
        )
        message_name_bytes = f"{message_name}_bytes"

        metadata = ApiMetadata(
            request_type=getattr(ProtocolMessageTypes, f.__name__),
            peer_required=peer_required,
            bytes_required=bytes_required,
            execute_task=execute_task,
            reply_types=non_optional_reply_types,
            message_class=message_class,
            # TODO: yep, i'm cheating at the moment
            node_type=None,  # type: ignore[arg-type]
        )

        _set_incomplete_metadata(function=wrapper, metadata=metadata)

        return wrapper

    return inner


def api_node() -> Callable[[Type[_T_NodeProtocol]], Type[_T_NodeProtocol]]:
    def decorator(cls: Type[_T_NodeProtocol]) -> Type[_T_NodeProtocol]:
        for attribute in vars(cls).values():
            metadata = get_metadata(attribute)

            if metadata is None:
                continue

            metadata.node_type = cls.node_type

            _set_metadata(function=attribute, metadata=replace(metadata, node_type=cls.node_type))

        return cls

    return decorator
