from dataclasses import replace
from typing import Any


def recursive_replace(root_obj: Any, replace_str: str, replace_with: Any):
    split_str = replace_str.split(".")
    if len(split_str) == 1:
        return replace(root_obj, **{split_str[0]: replace_with})
    sub_obj = recursive_replace(getattr(root_obj, split_str[0]), ".".join(split_str[1:]), replace_with)
    return replace(root_obj, **{split_str[0]: sub_obj})
