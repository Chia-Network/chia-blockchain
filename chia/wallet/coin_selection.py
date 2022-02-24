import logging
import random
from typing import Dict, List, Optional, Set

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64, uint128
from chia.wallet.wallet_coin_record import WalletCoinRecord


async def select_coins(
    spendable_amount: uint128,
    max_coin_amount: uint128,
    spendable_coins: List[WalletCoinRecord],
    unconfirmed_removals: Dict[bytes32, Coin],
    log: logging.Logger,
    amount: uint128,
    exclude: Optional[List[Coin]] = None,
) -> Set[Coin]:
    """
    Returns a set of coins that can be used for generating a new transaction.
    """
    if exclude is None:
        exclude = []

    if amount > spendable_amount:
        error_msg = (
            f"Can't select amount higher than our spendable balance.  Amount: {amount}, spendable: {spendable_amount}"
        )
        log.warning(error_msg)
        raise ValueError(error_msg)

    log.info(f"About to select coins for amount {amount}")

    sum_spendable_coins = 0
    valid_spendable_coins: List[Coin] = []

    for coin_record in spendable_coins:  # remove all the useless coins.
        if coin_record.coin.name() in unconfirmed_removals:
            continue
        if coin_record.coin in exclude:
            continue
        valid_spendable_coins.append(coin_record.coin)
        sum_spendable_coins += coin_record.coin.amount

    # This happens when we couldn't use one of the coins because it's already used
    # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
    if sum_spendable_coins < amount:
        raise ValueError(
            "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
        )

    # Sort the coins by amount
    valid_spendable_coins.sort(reverse=True, key=lambda r: r.amount)

    # check for exact 1 to 1 coin match.
    exact_match_coin: Optional[Coin] = check_for_exact_match(valid_spendable_coins, uint64(amount))
    if exact_match_coin:
        log.info(f"selected coin with an exact match: {exact_match_coin}")
        return {exact_match_coin}

    # Check for an exact match with all of the coins smaller than the amount.
    # If we have more, smaller coins than the amount we run the next algorithm.
    smaller_coin_sum = 0  # coins smaller than target.
    smaller_coins: Set[Coin] = set()
    for coin in valid_spendable_coins:
        if coin.amount < amount:
            smaller_coin_sum += coin.amount
            smaller_coins.add(coin)
    if smaller_coin_sum == amount:
        log.info(f"Selected all smaller coins because they equate to an exact match of the target.: {smaller_coins}")
        return smaller_coins
    elif smaller_coin_sum < amount:
        smallest_coin: Optional[Coin] = find_smallest_coin(valid_spendable_coins, amount, max_coin_amount)
        assert smallest_coin is not None
        log.info(f"Selected closest greater coin: {smallest_coin.name()}")
        return {smallest_coin}
    else:
        best_coin_set = knapsack_coin_algorithm(smaller_coins, amount, max_coin_amount)
        assert best_coin_set is not None
        log.info(f"Selected coins from knapsack algorithm: {best_coin_set}")
        return best_coin_set


# These algorithms were based off of the algorithms in:
# https://murch.one/wp-content/uploads/2016/11/erhardt2016coinselection.pdf

# we use this to check if one of the coins exactly matches the target.
def check_for_exact_match(coin_list: List[Coin], target: uint64) -> Optional[Coin]:
    for coin in coin_list:
        if coin.amount == target:
            return coin
    return None


# we use this to find an individual coin greater than the target but as close as possible to the target.
def find_smallest_coin(coin_list: List[Coin], target: uint128, max_coin_amount: int) -> Optional[Coin]:
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
def knapsack_coin_algorithm(smaller_coins: Set[Coin], target: uint128, max_coin_amount: int) -> Optional[Set[Coin]]:
    smaller_coins_sorted = sorted(smaller_coins, reverse=True, key=lambda r: r.amount)
    best_set_sum = max_coin_amount
    best_set_of_coins: Optional[Set[Coin]] = None
    for i in range(1000):
        # reset these variables every loop.
        selected_coins: Set[Coin] = set()
        selected_coins_sum = 0
        n_pass = 0
        target_reached = False
        while n_pass < 2 and not target_reached:
            for coin in smaller_coins_sorted:
                # run 2 passes where the first pass may select a coin 50% of the time.
                # the second pass runs to finish the set if the first pass didn't finish the set.
                # this makes each trial random and increases the chance of getting a perfect set.
                if (n_pass == 0 and bool(random.getrandbits(1))) or (n_pass == 1 and coin not in selected_coins):
                    selected_coins_sum += coin.amount
                    selected_coins.add(coin)
                    if selected_coins_sum == target:
                        return selected_coins
                    if selected_coins_sum > target:
                        target_reached = True
                        if selected_coins_sum < best_set_sum:
                            best_set_of_coins = selected_coins.copy()
                            best_set_sum = selected_coins_sum
                            selected_coins_sum -= coin.amount
                            selected_coins.remove(coin)
            n_pass += 1
    return best_set_of_coins
