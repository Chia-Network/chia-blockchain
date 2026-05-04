from __future__ import annotations

import logging
import random

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64, uint128

from chia.types.blockchain_format.coin import Coin
from chia.wallet.util.tx_config import CoinSelectionConfig
from chia.wallet.wallet_coin_record import WalletCoinRecord


async def select_coins(
    spendable_amount: uint128,
    coin_selection_config: CoinSelectionConfig,
    spendable_coins: list[WalletCoinRecord],
    unconfirmed_removals: dict[bytes32, Coin],
    log: logging.Logger,
    amount: uint128,
) -> set[Coin]:
    """
    Returns a set of coins that can be used for generating a new transaction.
    """
    if amount > spendable_amount:
        error_msg = (
            f"Can't select amount higher than our spendable balance.  Amount: {amount}, spendable: {spendable_amount}"
        )
        log.warning(error_msg)
        raise ValueError(error_msg)

    log.debug(f"About to select coins for amount {amount}")

    max_num_coins = 500
    confirmed_spendable_coins = {cr for cr in spendable_coins if cr.coin.name() not in unconfirmed_removals}
    valid_spendable_coins: list[Coin] = list(
        coin_selection_config.filter_coins({cr.coin for cr in confirmed_spendable_coins})
    )
    sum_spendable_coins = sum(coin.amount for coin in valid_spendable_coins)

    # This happens when we couldn't use one of the coins because it's already used
    # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
    if sum_spendable_coins < amount:
        raise ValueError(
            f"Transaction for {amount} is greater than max spendable balance in a block of {sum_spendable_coins}. "
            "There may be other transactions pending or our minimum coin amount is too high."
        )
    if amount == 0 and len(spendable_coins) == 0:
        raise ValueError(
            "No coins available to spend, you can not create a coin with an amount of 0, without already having coins."
        )

    # Try to use the coins that must be included
    coins_that_must_be_included = coin_selection_config.included_coin_ids + (
        [coin_selection_config.primary_coin] if coin_selection_config.primary_coin is not None else []
    )
    included_coins = {coin for coin in valid_spendable_coins if coin.name() in coins_that_must_be_included}
    included_coin_sum = sum(coin.amount for coin in included_coins)
    if included_coin_sum >= amount and len(included_coins) > 0:
        return included_coins
    remaining_amount = uint128(amount - included_coin_sum)
    if included_coins != set():
        log.debug(f"Using included coins: {included_coins} and proceeding with selection of amount: {remaining_amount}")
    valid_spendable_coins = list(coin for coin in valid_spendable_coins if coin not in included_coins)

    # Sort the coins by amount
    valid_spendable_coins.sort(reverse=True, key=lambda r: r.amount)

    if coins_that_must_be_included == []:
        # check for exact 1 to 1 coin match.
        exact_match_coin: Coin | None = check_for_exact_match(valid_spendable_coins, uint64(remaining_amount))
        if exact_match_coin:
            log.debug(f"selected coin with an exact match: {exact_match_coin}")
            return included_coins | {exact_match_coin}

    # Check for an exact match with all of the coins smaller than the amount.
    # If we have more, smaller coins than the amount we run the next algorithm.
    smaller_coin_sum = 0  # coins smaller than target.
    smaller_coins: list[Coin] = []
    for coin in valid_spendable_coins:
        if coin.amount < remaining_amount:
            smaller_coin_sum += coin.amount
            smaller_coins.append(coin)
    if smaller_coin_sum == remaining_amount and len(smaller_coins) < max_num_coins and remaining_amount != 0:
        log.debug(f"Selected all smaller coins because they equate to an exact match of the target.: {smaller_coins}")
        return included_coins | set(smaller_coins)
    elif smaller_coin_sum < remaining_amount:
        smallest_coin: Coin | None = select_smallest_coin_over_target(remaining_amount, valid_spendable_coins)
        assert smallest_coin is not None  # Since we know we have enough, there must be a larger coin
        log.debug(f"Selected closest greater coin: {smallest_coin.name()}")
        return included_coins | {smallest_coin}
    elif smaller_coin_sum > remaining_amount:
        coin_set: set[Coin] | None = knapsack_coin_algorithm(
            smaller_coins, remaining_amount, coin_selection_config.max_coin_amount, max_num_coins
        )
        log.debug(f"Selected coins from knapsack algorithm: {coin_set}")
        if coin_set is None:
            coin_set = sum_largest_coins(remaining_amount, smaller_coins)
            if coin_set is None or len(coin_set) + len(list(included_coins)) > max_num_coins:
                greater_coin = select_smallest_coin_over_target(remaining_amount, valid_spendable_coins)
                if greater_coin is None:
                    raise ValueError(
                        f"Transaction of {remaining_amount} mojo would use more than "
                        f"{max_num_coins} coins. Try sending a smaller amount"
                    )
                coin_set = {greater_coin}
        return included_coins | coin_set
    else:
        # if smaller_coin_sum == amount and (len(smaller_coins) >= max_num_coins or amount == 0)
        potential_large_coin: Coin | None = select_smallest_coin_over_target(remaining_amount, valid_spendable_coins)
        if potential_large_coin is None:
            raise ValueError("Too many coins are required to make this transaction")
        log.debug(f"Resorted to selecting smallest coin over target due to dust.: {potential_large_coin}")
        return included_coins | {potential_large_coin}


# These algorithms were based off of the algorithms in:
# https://murch.one/wp-content/uploads/2016/11/erhardt2016coinselection.pdf


# we use this to check if one of the coins exactly matches the target.
def check_for_exact_match(coin_list: list[Coin], target: uint64) -> Coin | None:
    for coin in coin_list:
        if coin.amount == target:
            return coin
    return None


# amount of coins smaller than target, followed by a list of all valid spendable coins.
# Coins must be sorted in descending amount order.
def select_smallest_coin_over_target(target: uint128, sorted_coin_list: list[Coin]) -> Coin | None:
    if sorted_coin_list[0].amount < target:
        return None
    for coin in reversed(sorted_coin_list):
        if coin.amount >= target:
            return coin
    assert False  # Should never reach here


# we use this to find the set of coins which have total value closest to the target, but at least the target.
# IMPORTANT: The coins have to be sorted in descending order or else this function will not work.
def knapsack_coin_algorithm(
    smaller_coins: list[Coin], target: uint128, max_coin_amount: int, max_num_coins: int, seed: bytes = b"knapsack seed"
) -> set[Coin] | None:
    best_set_sum = max_coin_amount
    best_set_of_coins: set[Coin] | None = None
    ran: random.Random = random.Random()
    ran.seed(seed)
    for i in range(1000):
        # reset these variables every loop.
        selected_coins: set[Coin] = set()
        selected_coins_sum = 0
        n_pass = 0
        target_reached = False
        while n_pass < 2 and not target_reached:
            for coin in smaller_coins:
                # run 2 passes where the first pass may select a coin 50% of the time.
                # the second pass runs to finish the set if the first pass didn't finish the set.
                # this makes each trial random and increases the chance of getting a perfect set.
                if (n_pass == 0 and bool(ran.getrandbits(1))) or (n_pass == 1 and coin not in selected_coins):
                    if len(selected_coins) > max_num_coins:
                        break
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


# Adds up the largest coins in the list, resulting in the minimum number of selected coins. A solution
# is guaranteed if and only if the sum(coins) >= target. Coins must be sorted in descending amount order.
def sum_largest_coins(target: uint128, sorted_coins: list[Coin]) -> set[Coin] | None:
    total_value = 0
    selected_coins: set[Coin] = set()
    for coin in sorted_coins:
        total_value += coin.amount
        selected_coins.add(coin)
        if total_value >= target:
            return selected_coins
    return None
