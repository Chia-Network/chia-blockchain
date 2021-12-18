from typing import Dict

import chia.consensus.default_constants


DEFAULT_CONSTANTS = chia.consensus.default_constants.DEFAULT_CONSTANTS
ConsensusConstants = chia.consensus.default_constants.ConsensusConstants


def make_test_constants(test_constants_overrides: Dict) -> ConsensusConstants:
    return DEFAULT_CONSTANTS.replace(**test_constants_overrides)
