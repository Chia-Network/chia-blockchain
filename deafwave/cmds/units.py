from typing import Dict

# The rest of the codebase uses mojos everywhere. Only uses these units
# for user facing interfaces
units: Dict[str, int] = {
    "deafwave": 10 ** 12,  # 1 deafwave (ZZZ) is 1,000,000,000,000 mojo (1 trillion)
    "mojo:": 1,
    "colouredcoin": 10 ** 3,  # 1 coloured coin is 1000 colouredcoin mojos
}
