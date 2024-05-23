from __future__ import annotations

import logging
from typing import Any

from chia_rs import ConsensusConstants as ConsensusConstants

from chia.util.byte_types import hexstr_to_bytes

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

    # TODO: this is too magical here and is really only used for configuration unmarshalling
    return constants.replace(**filtered_changes)  # type: ignore[arg-type]
