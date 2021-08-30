from typing import Dict

# The rest of the codebase uses ch everywhere.
# Only use these units for user facing interfaces.
units: Dict[str, int] = {
    "flange": 10 ** 12,  # 1 flange (fln) is 1,000,000,000,000 ch (1 trillion)
    "ch:": 1,
    "colouredcoin": 10 ** 3,  # 1 coloured coin is 1000 colouredcoin ch
}
