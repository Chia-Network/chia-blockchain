import functools
from inspect import signature
import logging

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
        log.info(f"<- {f.__name__}")
        return f(**inter)
    return f_substitute
