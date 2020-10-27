from typing import Dict

from src.consensus.constants import constants


def make_test_constants(test_constants_overrides: Dict):
    return constants.replace(**test_constants_overrides)
