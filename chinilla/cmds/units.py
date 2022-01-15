from typing import Dict

# The rest of the codebase uses chins everywhere.
# Only use these units for user facing interfaces.
units: Dict[str, int] = {
    "chinilla": 10 ** 12,  # 1 chinilla (XCHI) is 1,000,000,000,000 chin (1 trillion)
    "chin": 1,
    "colouredcoin": 10 ** 3,  # 1 coloured coin is 1000 colouredcoin chins
}
