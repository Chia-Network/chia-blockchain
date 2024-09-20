from __future__ import annotations

import logging
from typing import Any

from chia_rs import ConsensusConstants as ConsensusConstants

from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash

log = logging.getLogger(__name__)


def replace_str_to_bytes(constants: ConsensusConstants, **changes: Any) -> ConsensusConstants:
    """
    Overrides str (hex) values with bytes.
    """

    filtered_changes = {}
    for k, v in changes.items():
        if not hasattr(constants, k):
            # NETWORK_TYPE used to be present in default config, but has been removed
            if k not in ["NETWORK_TYPE"]:
                log.warning(f'invalid key in network configuration (config.yaml) "{k}". Ignoring')
            continue
        if isinstance(v, str):
            filtered_changes[k] = hexstr_to_bytes(v)
        else:
            filtered_changes[k] = v

    # if we override the additional data (replay protection across forks)
    # make sure the other variants of the AGG_SIG_* conditions are also covered
    if "AGG_SIG_ME_ADDITIONAL_DATA" in filtered_changes:
        AGG_SIG_DATA = filtered_changes["AGG_SIG_ME_ADDITIONAL_DATA"]
        if "AGG_SIG_PARENT_ADDITIONAL_DATA" not in filtered_changes:
            filtered_changes["AGG_SIG_PARENT_ADDITIONAL_DATA"] = std_hash(AGG_SIG_DATA + bytes([43]))
        if "AGG_SIG_PUZZLE_ADDITIONAL_DATA" not in filtered_changes:
            filtered_changes["AGG_SIG_PUZZLE_ADDITIONAL_DATA"] = std_hash(AGG_SIG_DATA + bytes([44]))
        if "AGG_SIG_AMOUNT_ADDITIONAL_DATA" not in filtered_changes:
            filtered_changes["AGG_SIG_AMOUNT_ADDITIONAL_DATA"] = std_hash(AGG_SIG_DATA + bytes([45]))
        if "AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA" not in filtered_changes:
            filtered_changes["AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA"] = std_hash(AGG_SIG_DATA + bytes([46]))
        if "AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA" not in filtered_changes:
            filtered_changes["AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA"] = std_hash(AGG_SIG_DATA + bytes([47]))
        if "AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA" not in filtered_changes:
            filtered_changes["AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA"] = std_hash(AGG_SIG_DATA + bytes([48]))

    # TODO: this is too magical here and is really only used for configuration unmarshalling
    return constants.replace(**filtered_changes)  # type: ignore[arg-type]
