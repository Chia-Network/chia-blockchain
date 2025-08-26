from __future__ import annotations

import functools
import inspect
import logging
import re
import textwrap
from collections.abc import Awaitable
from dataclasses import dataclass, field
from logging import Logger
from typing import Callable, ClassVar, Optional, TypeVar, Union, final, get_type_hints

from typing_extensions import Concatenate, ParamSpec, Protocol

from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.streamable import Streamable


class ApiSchemaProtocol(Protocol):
    metadata: ClassVar[ApiMetadata]


class ApiProtocol(ApiSchemaProtocol, Protocol):
    log: Logger

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

    def create_schema(self, api: type[ApiProtocol]) -> str:
        # ruff will fixup imports
        import_lines = [
            "from __future__ import annotations",
            "from typing import TYPE_CHECKING, ClassVar, Optional, cast",
            "from chia_rs import RespondToPhUpdates",
            "from chia.protocols.outbound_message import Message",
            "from chia.protocols.protocol_message_types import ProtocolMessageTypes",
            "from chia.server.api_protocol import ApiMetadata, ApiSchemaProtocol",
            "from chia.server.ws_connection import WSChiaConnection",
        ]

        schema_class_name = api.__name__.replace("API", "ApiSchema")
        class_lines = (
            textwrap.dedent(
                f"""
            class {schema_class_name}:
                if TYPE_CHECKING:
                    _protocol_check: ApiSchemaProtocol = cast("{schema_class_name}", None)

                metadata: ClassVar[ApiMetadata] = ApiMetadata()
            """
            )
            .strip()
            .splitlines()
        )

        method_lines = []

        # First pass: collect method signatures and track usage
        for request in self.message_type_to_request.values():
            type_hints = get_type_hints(request.method)
            source = inspect.getsource(request.method).splitlines()

            # Collect the method signature lines
            method_source = []
            for line in source:
                method_source.append(line)
                if line.rstrip().endswith(":"):
                    break

            this_method_schema_source = "\n".join(method_source)

            # Check for types used in parameters that appear in the signature
            for param_name, hint in type_hints.items():
                if param_name in {"self", "return"}:
                    continue

                module = hint.__module__
                name = hint.__name__
                protocol_match = re.match(r"(?P<base>chia\.protocols)\.(?P<protocol>[^. ]+_protocol)", module)
                # Import from chia.protocols.*
                if protocol_match is not None:
                    base = protocol_match.group("base")
                    protocol = protocol_match.group("protocol")
                    if re.search(rf"(?<!\.){name}\b", this_method_schema_source) is not None:
                        import_lines.append(f"from {base}.{protocol} import {name}")
                    if re.search(rf"(?<!\.){protocol}\b", this_method_schema_source) is not None:
                        import_lines.append(f"from {base} import {protocol}")

            # Check if method has a non-None return type that requires an ignore comment
            return_hint = type_hints.get("return")
            needs_ignore = False

            if return_hint is not None and return_hint is not type(None):
                # Check if it's Optional[something] - Optional types are fine with "..."
                origin = getattr(return_hint, "__origin__", None)
                if origin is Union:
                    if type(None) not in return_hint.__args__:
                        # Not Optional (e.g., just Message), needs ignore
                        needs_ignore = True
                    # else: is Optional, no ignore needed
                else:
                    # Direct return type (not Optional), needs ignore
                    needs_ignore = True

            for line in source:
                stripped = line.strip()
                final_line = line
                if stripped.startswith(("async def", "def")):
                    if needs_ignore:
                        final_line = final_line.rstrip() + "  # type: ignore[empty-body]"

                method_lines.append(final_line.rstrip())
                if stripped.endswith(":"):
                    break

            method_lines.append("        ...")
            method_lines.append("")

        lines = [*import_lines, "", *class_lines, "", *method_lines]

        return "\n".join(lines)
