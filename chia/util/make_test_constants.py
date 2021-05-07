from typing import Dict

from chia.consensus.default_constants import DEFAULT_CONSTANTS, ConsensusConstants


def make_test_constants(test_constants_overrides: Dict) -> ConsensusConstants:
    return DEFAULT_CONSTANTS.replace(**test_constants_overrides)
