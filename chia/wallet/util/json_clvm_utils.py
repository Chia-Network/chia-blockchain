from __future__ import annotations

from typing import Any

from chia.types.blockchain_format.program import Program


def json_to_chialisp(json_data: Any) -> Any:
    list_for_chialisp = []
    if isinstance(json_data, list):
        for value in json_data:
            list_for_chialisp.append(json_to_chialisp(value))
    else:
        if isinstance(json_data, dict):
            for key, value in json_data:
                list_for_chialisp.append((key, json_to_chialisp(value)))
        else:
            list_for_chialisp = json_data
    return Program.to(list_for_chialisp)
