import asyncio
import dataclasses
from pathlib import Path
from typing import Any, Dict, Tuple

from src.consensus.constants import ConsensusConstants
from src.util.config import load_config


async def wait_for_genesis_challenge(root_path: Path, constants: ConsensusConstants) -> Tuple[Dict, ConsensusConstants]:
    while True:
        await asyncio.sleep(1)
        config = load_config(root_path, "config.yaml")
        selected = config["selected_network"]
        challenge = config["network_overrides"][selected]["constants"]["GENESIS_CHALLENGE"]
        if challenge is None:
            continue
        else:
            # dataclasses.replace(constants, GENESIS_CHALLENGE=challenge)
            # constants.GENESIS_CHALLENGE = challenge
            overrides = config["network_overrides"]["constants"][config["selected_network"]]
            updated_constants = constants.replace_str_to_bytes(**overrides)
            return config, updated_constants
