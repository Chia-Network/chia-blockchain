import functools
import logging
from inspect import signature

log = logging.getLogger(__name__)


def api_request(f):
    """
    This decorator will log the request.
    @api_request
    def new_challenge(challenge):
        # handle request
    """

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
            if param_name != "return" and isinstance(inter[param_name], dict):
                inter[param_name] = param_class(**inter[param_name])

        return f(**inter)

    return f_substitute
