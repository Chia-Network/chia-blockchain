from typing import Dict

from src.consensus.default_constants import DEFAULT_CONSTANTS


def make_test_constants(test_constants_overrides: Dict):
    return DEFAULT_CONSTANTS.replace(**test_constants_overrides)
