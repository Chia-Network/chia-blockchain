from typing import Any, List, Tuple

from typing_extensions import Protocol

from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.wallet.action_manager.coin_info import CoinInfo
from chia.wallet.puzzle_drivers import Solver


class OuterWallet(Protocol):
    @staticmethod
    async def select_coins_from_spend_descriptions(
        wallet_state_manager: Any, coin_spec: Solver, previous_actions: List[SpendDescription]
    ) -> Tuple[List[CoinInfo], Optional[Solver]]:
        ...

    @staticmethod
    async def select_new_coins(
        wallet_state_manager: Any, coin_spec: Solver, exclude: List[Coin] = []
    ) -> List[CoinInfo]:
        ...
