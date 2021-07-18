from typing import Dict

# The rest of the codebase uses mtads everywhere.
# Only use these units for user facing interfaces.
units: Dict[str, int] = {
    "tad": 10 ** 12,  # 1 tadcoin (TAD) is 1,000,000,000,000 mtad (1 trillion)
    "mtad:": 1,
    "colouredcoin": 10 ** 3,  # 1 coloured coin is 1000 colouredcoin mtads
}
