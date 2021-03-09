import asyncio
from pathlib import Path
from typing import Dict, Tuple

from src.consensus.constants import ConsensusConstants
from src.util.config import load_config


async def wait_for_genesis_challenge(
    root_path: Path, constants: ConsensusConstants, SERVICE_NAME
) -> Tuple[Dict, ConsensusConstants]:
    while True:
        await asyncio.sleep(1)
        config = load_config(root_path, "config.yaml", SERVICE_NAME)
        selected = config["selected_network"]
        challenge = config["network_overrides"]["constants"][selected]["GENESIS_CHALLENGE"]
        if challenge is None:
            continue
        else:
            overrides = config["network_overrides"]["constants"][config["selected_network"]]
            updated_constants = constants.replace_str_to_bytes(**overrides)
            return config, updated_constants
