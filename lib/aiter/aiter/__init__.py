"Useful patterns building upon asynchronous iterators"

__version__ = "0.1.2"


__all__ = [
    "active_aiter", "aiter_forker", "aiter_to_iter", "azip", "flatten_aiter", "gated_aiter",
    "iter_to_aiter", "join_aiters", "map_aiter", "map_filter_aiter", "preload_aiter",
    "push_aiter", "sharable_aiter", "stoppable_aiter"
]

for _ in __all__:
    exec("from .%s import %s" % (_, _))
