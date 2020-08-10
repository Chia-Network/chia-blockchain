import datetime
import json

from typing import Any, Optional


class JSONMessage:
    def __init__(self, d):
        self.d = d

    @classmethod
    def deserialize(cls, blob):
        return cls.deserialize_text(blob.decode("utf8"))

    @classmethod
    def deserialize_text(cls, text):
        return cls(json.loads(text))

    def serialize(self):
        return self.serialize_text().encode("utf8")

    def serialize_text(self):
        return json.dumps(self.d)

    @classmethod
    def for_invocation(cls, method_name, args, kwargs, source, target):
        d = dict(m=method_name)
        if args:
            d["a"] = args
        if kwargs:
            d["k"] = kwargs
        if source is not None:
            d["s"] = source
        if target is not None:
            d["t"] = target

        return cls(d)

    @classmethod
    def for_response(cls, target, r):
        return cls(dict(t=target, r=r))

    @classmethod
    def for_exception(cls, target, exception):
        return cls(dict(t=target, e=repr(exception)))

    def source(self):
        return self.d.get("s")

    def target(self):
        return self.d.get("t", 0)

    def method_name(self) -> Optional[str]:
        return self.d.get("m")

    def exception(self) -> Optional[Exception]:
        e_text = self.d.get("e")
        if e_text:
            return IOError(e_text)
        return None

    def response(self) -> Optional[Any]:
        return self.d.get("r")

    def args_and_kwargs(self):
        pair = (self.d.get("a", []), self.d.get("k", {}))
        return pair

    @classmethod
    def from_simple_types(cls, v, t, rpc_streamer):
        d = {
            None: lambda a: None,
            bool: lambda a: True if a else False,
            str: lambda a: a,
            int: lambda a: a,
            datetime.datetime: lambda v: datetime.datetime.fromtimestamp(float(v)),
        }
        return cls.convert_with_table(v, t, d)

    @classmethod
    def to_simple_types(cls, v, t, rpc_streamer):
        d = {
            None: lambda a: 0,
            bool: lambda a: 1 if a else 0,
            str: lambda a: a,
            int: lambda a: a,
            datetime.datetime: lambda v: str(v.timestamp()),
        }
        return cls.convert_with_table(v, t, d)

    @classmethod
    def convert_with_table(cls, v, t, lookup):
        f = lookup.get(t)
        if f:
            return f(v)
        raise TypeError(f"can't convert {v} to type {t}")
