import random
from typing import Set, Optional, List

from chia.types.blockchain_format.coin import Coin
from chia.util.ints import uint64

# These algorithms were based off of the algorithms in:
# https://murch.one/wp-content/uploads/2016/11/erhardt2016coinselection.pdf


# we use this to check if one of the coins exactly matches the target.
def check_for_exact_match(coin_list: List[Coin], target: uint64) -> Optional[Coin]:
    for coin in coin_list:
        if coin.amount == target:
            return coin
    return None


# we use this to find an individual coin greater than the target but as close as possible to the target.
def find_smallest_coin(coin_list: List[Coin], target: uint64, max_coin_amount: int) -> Optional[Coin]:
    smallest_value = max_coin_amount  # smallest coins value
    smallest_coin: Optional[Coin] = None
    for coin in coin_list:
        if target < coin.amount < smallest_value:
            # try to find a coin that is as close as possible to the amount.
            smallest_value = coin.amount
            smallest_coin = coin
    return smallest_coin


# we use this to find the set of coins which have total value closest to the target, but at least the target.
# coins should be sorted in descending order.
def knapsack_coin_algorithm(smaller_coins: Set[Coin], target: uint64, max_coin_amount: int) -> Optional[Set[Coin]]:
    smaller_coins_sorted = sorted(smaller_coins, reverse=True, key=lambda r: r.amount)
    best_set_sum = max_coin_amount
    best_set_of_coins: Optional[Set[Coin]] = None
    for i in range(1000):
        # reset these variables every loop.
        selected_coins: Set = set()
        selected_coins_sum = 0
        n_pass = 0
        target_reached = False
        while n_pass < 2 and not target_reached:
            for coin in smaller_coins_sorted:
                # run 2 passes where the first pass may select a coin 50% of the time.
                # the second pass runs to finish the set if the first pass didn't finish the set.
                # this makes each trial random and increases the chance of getting a perfect set.
                if (n_pass == 0 and bool(random.getrandbits(1))) or (coin not in selected_coins):
                    selected_coins_sum += coin.amount
                    selected_coins.add(coin)
                    if selected_coins_sum == target:
                        return selected_coins
                    if selected_coins_sum > target:
                        target_reached = True
                        if selected_coins_sum < best_set_sum:
                            best_set_of_coins = selected_coins
                            best_set_sum = selected_coins_sum
                            selected_coins_sum -= coin.amount
                            selected_coins.remove(coin)
            n_pass += 1
    return best_set_of_coins
