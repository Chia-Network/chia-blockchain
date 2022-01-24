import random
from typing import Set, Optional, Tuple, List
from chia.types.blockchain_format.coin import Coin
from chia.util.ints import uint64
from chia.wallet.wallet_coin_record import WalletCoinRecord


# we use this to check if one of the coins exactly matches the target.
def check_for_exact_match(coin_records: List[WalletCoinRecord], target: int) -> Optional[WalletCoinRecord]:
    for coinrecord in coin_records:
        if coinrecord.coin.amount == target:
            return coinrecord
    return None


# we use this to find the individual coin that is closest to the target amount.
def find_smallest_coin(coin_records: List[WalletCoinRecord], target: int) -> Optional[WalletCoinRecord]:
    smallest_value = float("inf")  # smallest coins value
    smallest_coin: Optional[WalletCoinRecord] = None
    for coinrecord in coin_records:
        if target < coinrecord.coin.amount < smallest_value:
            # try to find a coin that is as close as possible to the amount.
            smallest_value = coinrecord.coin.amount
            smallest_coin = coinrecord
    return smallest_coin


# we use this to find the smallest set of coins.
def knapsack_coin_algorithm(smaller_coins: Set[Coin], target: int) -> Tuple[Optional[Set[Coin]], uint64]:
    best_set_sum = float("inf")
    best_set_of_coins: Optional[Set[Coin]] = None
    for i in range(1000):
        n_pass = 0
        selected_coins: Set = set()
        target_reached = False
        selected_coins_sum = 0
        while n_pass < 2 and not target_reached:
            for coin in smaller_coins:
                if (n_pass == 0 and bool(random.getrandbits(1)) is True) or (
                    n_pass == 1 and coin not in selected_coins
                ):
                    selected_coins_sum += coin.amount
                    selected_coins.add(coin)
                    if selected_coins_sum == target:
                        return (selected_coins, uint64(selected_coins_sum))
                    if selected_coins_sum > target:
                        target_reached = True
                        if selected_coins_sum < best_set_sum:
                            best_set_of_coins = selected_coins
                            best_set_sum = selected_coins_sum
                            selected_coins_sum -= coin.amount
                            selected_coins.remove(coin)
                    n_pass += 1
    return (best_set_of_coins, uint64(int(best_set_sum)))
