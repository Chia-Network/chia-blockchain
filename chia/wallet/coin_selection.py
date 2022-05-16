import logging
import random
from typing import Dict, List, Optional, Set

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64, uint128
from chia.wallet.wallet_coin_record import WalletCoinRecord


async def select_coins(
    spendable_amount: uint128,
    max_coin_amount: int,
    spendable_coins: List[WalletCoinRecord],
    unconfirmed_removals: Dict[bytes32, Coin],
    log: logging.Logger,
    amount: uint128,
    exclude: Optional[List[Coin]] = None,
    min_coin_amount: Optional[uint128] = None,
) -> Set[Coin]:
    """
    Returns a set of coins that can be used for generating a new transaction.
    """
    if exclude is None:
        exclude = []
    if min_coin_amount is None:
        min_coin_amount = uint128(0)

    if amount > spendable_amount:
        error_msg = (
            f"Can't select amount higher than our spendable balance.  Amount: {amount}, spendable: {spendable_amount}"
        )
        log.warning(error_msg)
        raise ValueError(error_msg)

    log.debug(f"About to select coins for amount {amount}")

    max_num_coins = 500
    sum_spendable_coins = 0
    valid_spendable_coins: List[Coin] = []

    for coin_record in spendable_coins:  # remove all the unconfirmed coins, excluded coins and dust.
        if coin_record.coin.name() in unconfirmed_removals:
            continue
        if coin_record.coin in exclude:
            continue
        if coin_record.coin.amount < min_coin_amount:
            continue
        valid_spendable_coins.append(coin_record.coin)
        sum_spendable_coins += coin_record.coin.amount

    # This happens when we couldn't use one of the coins because it's already used
    # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
    if sum_spendable_coins < amount:
        raise ValueError(
            f"Transaction for {amount} is greater than spendable balance of {sum_spendable_coins}. "
            "There may be other transactions pending or our minimum coin amount is too high."
        )

    # Sort the coins by amount
    valid_spendable_coins.sort(reverse=True, key=lambda r: r.amount)

    # check for exact 1 to 1 coin match.
    exact_match_coin: Optional[Coin] = check_for_exact_match(valid_spendable_coins, uint64(amount))
    if exact_match_coin:
        log.debug(f"selected coin with an exact match: {exact_match_coin}")
        return {exact_match_coin}

    # Check for an exact match with all of the coins smaller than the amount.
    # If we have more, smaller coins than the amount we run the next algorithm.
    smaller_coin_sum = 0  # coins smaller than target.
    smaller_coins: List[Coin] = []
    for coin in valid_spendable_coins:
        if coin.amount < amount:
            smaller_coin_sum += coin.amount
            smaller_coins.append(coin)
    if smaller_coin_sum == amount and len(smaller_coins) < max_num_coins:
        log.debug(f"Selected all smaller coins because they equate to an exact match of the target.: {smaller_coins}")
        return set(smaller_coins)
    elif smaller_coin_sum < amount:
        smallest_coin = select_smallest_coin_over_target(len(smaller_coins), valid_spendable_coins)
        log.debug(f"Selected closest greater coin: {smallest_coin.name()}")
        return {smallest_coin}
    elif smaller_coin_sum > amount:
        coin_set = knapsack_coin_algorithm(smaller_coins, amount, max_coin_amount)
        log.debug(f"Selected coins from knapsack algorithm: {coin_set}")
        if coin_set is None:
            raise ValueError("Knapsack algorithm failed to find a solution.")
        if len(coin_set) > max_num_coins:
            coin = select_smallest_coin_over_target(len(smaller_coins), valid_spendable_coins)
            if coin is None or coin.amount < amount:
                raise ValueError(
                    f"Transaction of {amount} mojo would use more than "
                    f"{max_num_coins} coins. Try sending a smaller amount"
                )
            coin_set = {coin}
        return coin_set
    else:
        # if smaller_coin_sum == amount and len(smaller_coins) >= max_num_coins.
        coin = select_smallest_coin_over_target(len(smaller_coins), valid_spendable_coins)
        log.debug(f"Resorted to selecting smallest coin over target due to dust.: {coin}")
        return {coin}


# These algorithms were based off of the algorithms in:
# https://murch.one/wp-content/uploads/2016/11/erhardt2016coinselection.pdf

# we use this to check if one of the coins exactly matches the target.
def check_for_exact_match(coin_list: List[Coin], target: uint64) -> Optional[Coin]:
    for coin in coin_list:
        if coin.amount == target:
            return coin
    return None


# amount of coins smaller than target, followed by a list of all valid spendable coins sorted in descending order.
def select_smallest_coin_over_target(smaller_coin_amount: int, valid_spendable_coin_list: List[Coin]) -> Coin:
    if smaller_coin_amount >= len(valid_spendable_coin_list):
        raise ValueError("Unable to select coins for this transaction. Try sending a smaller amount")
    if smaller_coin_amount > 0:  # in case we only have bigger coins.
        greater_coins = valid_spendable_coin_list[:-smaller_coin_amount]
    else:
        greater_coins = valid_spendable_coin_list
    coin = greater_coins[len(greater_coins) - 1]  # select the coin with the least value.
    return coin


# we use this to find the set of coins which have total value closest to the target, but at least the target.
# IMPORTANT: The coins have to be sorted in descending order or else this function will not work.
def knapsack_coin_algorithm(smaller_coins: List[Coin], target: uint128, max_coin_amount: int) -> Optional[Set[Coin]]:
    best_set_sum = max_coin_amount
    best_set_of_coins: Optional[Set[Coin]] = None
    for i in range(1000):
        # reset these variables every loop.
        selected_coins: Set[Coin] = set()
        selected_coins_sum = 0
        n_pass = 0
        target_reached = False
        while n_pass < 2 and not target_reached:
            for coin in smaller_coins:
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
