import functools
import logging
from inspect import signature

from chia.util.streamable import Streamable

log = logging.getLogger(__name__)


BYTES_REQUIRED = "bytes_required"
PEER_REQUIRED = "peer_required"
EXECUTE_TASK = "execute_task"
MSG_REPLY_TYPE = "msg_reply_type"
API_FUNCTION = "api_function"


def api_request(f):
    @functools.wraps(f)
    def f_substitute(*args, **kwargs):
        sig = signature(f)
        binding = sig.bind(*args, **kwargs)
        binding.apply_defaults()
        inter = dict(binding.arguments)

        # Converts each parameter from a Python dictionary, into an instance of the object
        # specified by the type annotation (signature) of the function that is being called (f)
        # The method can also be called with the target type instead of a dictionary.
        for param_name, param_class in f.__annotations__.items():
            if param_name != "return" and isinstance(inter[param_name], Streamable):
                if param_class.__name__ == "bytes":
                    continue
                if hasattr(f, BYTES_REQUIRED):
                    inter[f"{param_name}_bytes"] = bytes(inter[param_name])
                    continue
            if param_name != "return" and isinstance(inter[param_name], bytes):
                if param_class.__name__ == "bytes":
                    continue
                if hasattr(f, BYTES_REQUIRED):
                    inter[f"{param_name}_bytes"] = inter[param_name]
                if inter[param_name] == b"":
                    inter[param_name] = None
                else:
                    inter[param_name] = param_class.from_bytes(inter[param_name])
        return f(**inter)

    setattr(f_substitute, API_FUNCTION, True)
    return f_substitute


def peer_required(func):
    def inner():
        setattr(func, PEER_REQUIRED, True)
        return func

    return inner()


def bytes_required(func):
    def inner():
        setattr(func, BYTES_REQUIRED, True)
        return func

    return inner()


def execute_task(func):
    def inner():
        setattr(func, EXECUTE_TASK, True)
        return func

    return inner()


def msg_reply_type(type):
    def wrap(func):
        def inner():
            setattr(func, MSG_REPLY_TYPE, type)
            return func

        return inner()

    return wrap
