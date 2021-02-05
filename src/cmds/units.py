from typing import Dict

# The rest of the codebase uses mojos everywhere. Only uses these units
# for user facing interfaces
units: Dict[str, int] = {
    "chia": 10 ** 12,  # 1 chia (XCH) is 1,000,000,000,000 mojo (1 Trillion)
    "mojo:": 1,
    "colouredcoin": 10 ** 3,  # 1 coloured coin is 1000 colouredcoin mojos
}
