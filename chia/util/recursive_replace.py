from __future__ import annotations

from dataclasses import replace
from typing import Any


def recursive_replace(root_obj: Any, replace_str: str, replace_with: Any) -> Any:
    split_str = replace_str.split(".")
    if len(split_str) == 1:
        # This check is here to support native types (implemented in Rust
        # in chia_rs) that aren't dataclasses. They instead implement a
        # replace() method in their python bindings.
        if hasattr(root_obj, "replace"):
            return root_obj.replace(**{split_str[0]: replace_with})
        else:
            return replace(root_obj, **{split_str[0]: replace_with})
    sub_obj = recursive_replace(getattr(root_obj, split_str[0]), ".".join(split_str[1:]), replace_with)
    # See comment above
    if hasattr(root_obj, "replace"):
        return root_obj.replace(**{split_str[0]: sub_obj})
    else:
        return replace(root_obj, **{split_str[0]: sub_obj})
