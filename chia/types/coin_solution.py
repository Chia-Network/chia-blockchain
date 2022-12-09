from __future__ import annotations

import warnings

from .coin_spend import CoinSpend as CoinSolution  # noqa lgtm[py/unused-import]

warnings.warn("`CoinSolution` is now `CoinSpend`")
