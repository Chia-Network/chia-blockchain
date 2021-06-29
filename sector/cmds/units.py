from typing import Dict

# The rest of the codebase uses octets everywhere.
# Only use these units for user facing interfaces.
units: Dict[str, int] = {
    "sector": 10 ** 12,  # 1 sector (XSC) is 1,000,000,000,000 octet (1 trillion)
    "octet:": 1,
    "colouredcoin": 10 ** 3,  # 1 coloured coin is 1000 colouredcoin octets
}
