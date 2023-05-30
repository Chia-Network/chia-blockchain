from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from typing_extensions import TypedDict

from chia.pools.pool_config import PoolWalletConfig
from chia.util.ints import uint8, uint64


class PoolState(TypedDict):
    p2_singleton_puzzle_hash: str
    points_found_since_start: uint64
    points_found_24h: List[Tuple[float, uint64]]
    points_acknowledged_since_start: uint64
    points_acknowledged_24h: List[Tuple[float, uint64]]
    next_farmer_update: float
    next_pool_info_update: float
    current_points: uint64
    current_difficulty: Optional[uint64]
    pool_errors_24h: List[Dict[str, Any]]
    authentication_token_timeout: Optional[uint8]
    pool_config: PoolWalletConfig
    plot_count: int
