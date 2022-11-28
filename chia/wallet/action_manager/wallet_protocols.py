from typing import Any, Callable, Dict, List, Tuple

from typing_extensions import Protocol

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.wallet.action_manager.coin_info import CoinInfo
from chia.wallet.puzzle_drivers import Solver


class OuterWallet(Protocol):
    @staticmethod
    def get_asset_types(request: Solver) -> Solver:
        ...

    @staticmethod
    async def match_asset_types(asset_types: List[Solver]) -> bool:
        ...

    @staticmethod
    async def select_coins_from_spend(
        wallet_state_manager: Any, coin_spec: Solver, previous_actions: List[CoinSpend]
    ) -> Tuple[List[CoinInfo], Optional[Solver]]:
        ...

    @staticmethod
    async def select_new_coins(
        wallet_state_manager: Any, coin_spec: Solver, exclude: List[Coin] = []
    ) -> List[CoinInfo]:
        ...

    @staticmethod
    async def match_spend(
        wallet_state_manager: Any, spend: CoinSpend, mod: Program, curried_args: Program
    ) -> Optional[Tuple[CoinInfo, List[WalletAction], List[Tuple[G1Element, bytes, bool]]]]:
        ...


class InnerWallet(Protocol):
    @staticmethod
    async def match_inner_puzzle_and_solution(
        wallet_state_manager: Any,
        puzzle: Program,
        solution: Program,
        mod: Program,
        curried_args: Program,
    ) -> Optional[Tuple[InnerDriver, List[WalletAction], List[Tuple[G1Element, bytes, bool]], Solver]]:
        ...