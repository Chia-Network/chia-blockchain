from typing import Dict

# The rest of the codebase uses chins everywhere.
# Only use these units for user facing interfaces.
units: Dict[str, int] = {
    "chinilla": 10 ** 12,  # 1 chia (XCH) is 1,000,000,000,000 mojo (1 trillion)
    "chin": 1,
    "cat": 10 ** 3,  # 1 CAT is 1000 CAT mojos
}
