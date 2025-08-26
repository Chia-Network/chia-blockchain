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
            # print(inspect.getsource(f))
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
        imports = set()
        imports.add("from __future__ import annotations")
        imports.add("from chia.server.api_protocol import ApiMetadata, ApiSchemaProtocol")

        # Track what's actually referenced in the generated code
        used_types = set()
        method_lines = []

        # First pass: collect method signatures and track usage
        for request in self.message_type_to_request.values():
            type_hints = get_type_hints(request.method)
            source = inspect.getsourcelines(request.method)[0]

            # Collect the method signature lines
            method_source = []
            for line in source:
                method_source.append(line)
                if line.rstrip().endswith(":"):
                    break
            method_lines.extend(method_source)

            # Check return type for Optional and Message
            return_hint = type_hints.get("return")
            if return_hint:
                origin = getattr(return_hint, "__origin__", None)
                if origin is Union:
                    args = return_hint.__args__
                    if type(None) in args:
                        used_types.add("Optional")
                    for arg in args:
                        if arg.__name__ == "Message":
                            used_types.add("Message")
                elif return_hint.__name__ == "Message":
                    used_types.add("Message")

            # Check for types used in parameters that appear in the signature
            for param_name, hint in type_hints.items():
                if param_name not in {"self", "return"}:
                    module = hint.__module__
                    name = hint.__name__
                    if module and module.startswith("chia."):
                        # Check if the type name actually appears directly in the method signature
                        # (not as part of harvester_protocol.ClassName)
                        signature_text = "".join(method_source)
                        # Only import if used directly, not through module qualification
                        if f": {name}" in signature_text or f"-> {name}" in signature_text:
                            used_types.add(name)
                            imports.add(f"from {module} import {name}")

            # Check decorators for ProtocolMessageTypes usage
            decorator_line = source[0].strip()
            if "ProtocolMessageTypes." in decorator_line:
                used_types.add("ProtocolMessageTypes")
                imports.add("from chia.protocols.protocol_message_types import ProtocolMessageTypes")

            # Check for protocol module usage in the signature
            for line in method_source:
                # Look for any protocol module usage (e.g., farmer_protocol.*, full_node_protocol.*, etc.)
                protocol_matches = re.findall(r"(\w+_protocol)\.", line)
                for protocol_module in protocol_matches:
                    imports.add(f"from chia.protocols import {protocol_module}")

                # Also check for types that might be from protocol modules but used directly
                # Look for CamelCase types that aren't already imported
                type_matches = re.findall(r": ([A-Z][a-zA-Z]+)", line)
                for type_name in type_matches:
                    if type_name not in used_types and type_name not in {"Optional", "Message", "WSChiaConnection"}:
                        # This might be a direct import we missed
                        # Try to find it in the type hints
                        for param_name, hint in type_hints.items():
                            name = hint.__name__
                            module = hint.__module__
                            if name == type_name and module:
                                # Import from chia.protocols.*
                                if module.startswith("chia.protocols."):
                                    imports.add(f"from {module} import {name}")
                                    used_types.add(name)
                                # Special case: chia_rs types show up as builtins but are actually from chia_rs
                                elif module == "builtins" and type_name in {"RespondToPhUpdates"}:
                                    imports.add(f"from chia_rs import {name}")
                                    used_types.add(name)

        # Add imports only for types that are actually used
        if "Optional" in used_types:
            imports.add("from typing import TYPE_CHECKING, ClassVar, Optional, cast")
        else:
            imports.add("from typing import TYPE_CHECKING, ClassVar, cast")

        if "Message" in used_types:
            imports.add("from chia.protocols.outbound_message import Message")

        # Build the schema content as a string
        lines = []

        # Add imports
        for import_line in sorted(imports):
            lines.append(import_line)
        lines.append("")

        # Use *ApiSchema naming convention for generated schemas
        schema_class_name = api.__name__.replace("API", "ApiSchema")
        lines.append(
            textwrap.dedent(
                f"""
                class {schema_class_name}:
                    if TYPE_CHECKING:
                        _protocol_check: ApiSchemaProtocol = cast("{schema_class_name}", None)

                    metadata: ClassVar[ApiMetadata] = ApiMetadata()
                """
            ).strip()
        )

        for request in self.message_type_to_request.values():
            source = inspect.getsource(request.method).splitlines()

            # Check if method has a non-None return type that requires an ignore comment
            type_hints = get_type_hints(request.method)
            return_hint = type_hints.get("return")
            needs_ignore = False

            if return_hint and return_hint is not type(None):
                # Check if it's Optional[something] - Optional types are fine with "..."
                if hasattr(return_hint, "__origin__") and return_hint.__origin__ is Union:
                    args = return_hint.__args__
                    if type(None) not in args:
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

                lines.append(final_line.rstrip())
                if stripped.endswith(":"):
                    break

            lines.append("        ...")
            lines.append("")

        return "\n".join(lines)
