from typing import Any, Optional, Type


class RPCMessage:
    @classmethod
    def deserialize(cls, blob):
        pass

    def serialize(self):
        pass

    @classmethod
    def for_invocation(cls, method_name, args, kwargs, source, target):
        pass

    @classmethod
    def for_response(cls, target, r):
        pass

    @classmethod
    def for_exception(cls, target, text):
        pass

    def source(self):
        pass

    def target(self):
        pass

    def exception(self) -> Optional[Exception]:
        pass

    def response(self) -> Optional[Any]:
        pass

    def method_name(self) -> Optional[str]:
        # return None if it's not a request
        pass

    def args_and_kwargs(self):
        pass

    def from_simple_types(self, v: Any, t: Type, rpc_streamer) -> Any:
        pass

    @classmethod
    def to_simple_types(cls: Type, v: Any, t: Type, rpc_streamer) -> Any:
        pass
