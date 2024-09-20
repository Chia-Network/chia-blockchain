from __future__ import annotations

import dataclasses
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from chia_rs import fast_forward_singleton, get_conditions_from_spendbundle

from chia.consensus.condition_costs import ConditionCost
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.internal_mempool_item import InternalMempoolItem
from chia.types.mempool_item import BundleCoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint32, uint64


@dataclasses.dataclass(frozen=True)
class EligibilityAndAdditions:
    is_eligible_for_dedup: bool
    spend_additions: List[Coin]
    is_eligible_for_ff: bool


def run_for_cost(
    puzzle_reveal: SerializedProgram, solution: SerializedProgram, additions_count: int, max_cost: int
) -> uint64:
    create_coins_cost = additions_count * ConditionCost.CREATE_COIN.value
    clvm_cost, _ = puzzle_reveal.run_mempool_with_cost(max_cost, solution)
    saved_cost = uint64(clvm_cost + create_coins_cost)
    return saved_cost


@dataclasses.dataclass(frozen=True)
class DedupCoinSpend:
    solution: SerializedProgram
    cost: Optional[uint64]


@dataclasses.dataclass(frozen=True)
class UnspentLineageInfo:
    coin_id: bytes32
    coin_amount: uint64
    parent_id: bytes32
    parent_amount: uint64
    parent_parent_id: bytes32


def set_next_singleton_version(
    current_singleton: Coin, singleton_additions: List[Coin], fast_forward_spends: Dict[bytes32, UnspentLineageInfo]
) -> None:
    """
    Finds the next version of the singleton among its additions and updates the
    fast forward spends, currently chained together, accordingly

    Args:
        current_singleton: the current iteration of the singleton
        singleton_additions: the additions of the current singleton
        fast_forward_spends: in-out parameter of the spends currently chained together

    Raises:
        ValueError if none of the additions are considered to be the singleton's
        next iteration
    """
    singleton_child = next(
        (addition for addition in singleton_additions if addition.puzzle_hash == current_singleton.puzzle_hash), None
    )
    if singleton_child is None:
        raise ValueError("Could not find fast forward child singleton.")
    # Keep track of this in order to chain the next ff
    fast_forward_spends[current_singleton.puzzle_hash] = UnspentLineageInfo(
        coin_id=singleton_child.name(),
        coin_amount=singleton_child.amount,
        parent_id=singleton_child.parent_coin_info,
        parent_amount=current_singleton.amount,
        parent_parent_id=current_singleton.parent_coin_info,
    )


def perform_the_fast_forward(
    unspent_lineage_info: UnspentLineageInfo,
    spend_data: BundleCoinSpend,
    fast_forward_spends: Dict[bytes32, UnspentLineageInfo],
) -> Tuple[CoinSpend, List[Coin]]:
    """
    Performs a singleton fast forward, including the updating of all previous
    additions to point to the most recent version, and updates the fast forward
    spends, currently chained together, accordingly

    Args:
        unspent_lineage_info: the singleton's most recent lineage information
        spend_data: the current spend's data
        fast_forward_spends: in-out parameter of the spends currently chained together

    Returns:
        CoinSpend: the new coin spend after performing the fast forward
        List[Coin]: the updated additions that point to the new coin to spend

    Raises:
        ValueError if none of the additions are considered to be the singleton's
        next iteration
    """
    new_coin = Coin(
        unspent_lineage_info.parent_id, spend_data.coin_spend.coin.puzzle_hash, unspent_lineage_info.coin_amount
    )
    new_parent = Coin(
        unspent_lineage_info.parent_parent_id,
        spend_data.coin_spend.coin.puzzle_hash,
        unspent_lineage_info.parent_amount,
    )
    # These hold because puzzle hash is not expected to change
    assert new_coin.name() == unspent_lineage_info.coin_id
    assert new_parent.name() == unspent_lineage_info.parent_id
    new_solution = SerializedProgram.from_bytes(
        fast_forward_singleton(spend=spend_data.coin_spend, new_coin=new_coin, new_parent=new_parent)
    )
    singleton_child = None
    patched_additions = []
    for addition in spend_data.additions:
        patched_addition = Coin(unspent_lineage_info.coin_id, addition.puzzle_hash, addition.amount)
        patched_additions.append(patched_addition)
        if addition.puzzle_hash == spend_data.coin_spend.coin.puzzle_hash:
            # We found the next version of this singleton
            singleton_child = patched_addition
    if singleton_child is None:
        raise ValueError("Could not find fast forward child singleton.")
    new_coin_spend = CoinSpend(new_coin, spend_data.coin_spend.puzzle_reveal, new_solution)
    # Keep track of this in order to chain the next ff
    fast_forward_spends[spend_data.coin_spend.coin.puzzle_hash] = UnspentLineageInfo(
        coin_id=singleton_child.name(),
        coin_amount=singleton_child.amount,
        parent_id=singleton_child.parent_coin_info,
        parent_amount=unspent_lineage_info.coin_amount,
        parent_parent_id=unspent_lineage_info.parent_id,
    )
    return new_coin_spend, patched_additions


@dataclasses.dataclass(frozen=True)
class EligibleCoinSpends:
    deduplication_spends: Dict[bytes32, DedupCoinSpend] = dataclasses.field(default_factory=dict)
    fast_forward_spends: Dict[bytes32, UnspentLineageInfo] = dataclasses.field(default_factory=dict)

    def get_deduplication_info(
        self, *, bundle_coin_spends: Dict[bytes32, BundleCoinSpend], max_cost: int
    ) -> Tuple[List[CoinSpend], uint64, List[Coin]]:
        """
        Checks all coin spends of a mempool item for deduplication eligibility and
        provides the caller with the necessary information that allows it to perform
        identical spend aggregation on that mempool item if possible

        Args:
            bundle_coin_spends: the mempool item's coin spends data
            max_cost: the maximum limit when running for cost

        Returns:
            List[CoinSpend]: list of unique coin spends in this mempool item
            uint64: the cost we're saving by deduplicating eligible coins
            List[Coin]: list of unique additions in this mempool item

        Raises:
            ValueError to skip the mempool item we're currently in, if it's
            attempting to spend an eligible coin with a different solution than the
            one we're already deduplicating on.
        """
        cost_saving = 0
        unique_coin_spends: List[CoinSpend] = []
        unique_additions: List[Coin] = []
        # Map of coin ID to deduplication information
        new_dedup_spends: Dict[bytes32, DedupCoinSpend] = {}
        # See if this item has coin spends that are eligible for deduplication
        for coin_id, spend_data in bundle_coin_spends.items():
            if not spend_data.eligible_for_dedup:
                unique_coin_spends.append(spend_data.coin_spend)
                unique_additions.extend(spend_data.additions)
                continue
            # See if we processed an item with this coin before
            dedup_coin_spend = self.deduplication_spends.get(coin_id)
            if dedup_coin_spend is None:
                # We didn't process an item with this coin before. If we end up including
                # this item, add this pair to deduplication_spends
                new_dedup_spends[coin_id] = DedupCoinSpend(spend_data.coin_spend.solution, None)
                unique_coin_spends.append(spend_data.coin_spend)
                unique_additions.extend(spend_data.additions)
                continue
            # See if the solution was identical
            current_solution, duplicate_cost = dataclasses.astuple(dedup_coin_spend)
            if current_solution != spend_data.coin_spend.solution:
                # It wasn't, so let's skip this whole item because it's relying on
                # spending this coin with a different solution and that would
                # conflict with the coin spends that we're deduplicating already
                # NOTE: We can miss an opportunity to deduplicate on other solutions
                # even if they end up saving more cost, as we're going for the first
                # solution we see from the relatively highest FPC item, to avoid
                # severe performance and/or time-complexity impact
                raise ValueError("Solution is different from what we're deduplicating on")
            # Let's calculate the saved cost if we never did that before
            if duplicate_cost is None:
                # See first if this mempool item had this cost computed before
                # This can happen if this item didn't get included in the previous block
                spend_cost = spend_data.cost
                if spend_cost is None:
                    spend_cost = run_for_cost(
                        puzzle_reveal=spend_data.coin_spend.puzzle_reveal,
                        solution=spend_data.coin_spend.solution,
                        additions_count=len(spend_data.additions),
                        max_cost=max_cost,
                    )
                    # Update this mempool item's coin spends map
                    bundle_coin_spends[coin_id] = BundleCoinSpend(
                        coin_spend=spend_data.coin_spend,
                        eligible_for_dedup=spend_data.eligible_for_dedup,
                        eligible_for_fast_forward=spend_data.eligible_for_fast_forward,
                        additions=spend_data.additions,
                        cost=spend_cost,
                    )
                duplicate_cost = spend_cost
                # If we end up including this item, update this entry's cost
                new_dedup_spends[coin_id] = DedupCoinSpend(current_solution, duplicate_cost)
            cost_saving += duplicate_cost
        # Update the eligible coin spends data
        self.deduplication_spends.update(new_dedup_spends)
        return unique_coin_spends, uint64(cost_saving), unique_additions

    async def process_fast_forward_spends(
        self,
        *,
        mempool_item: InternalMempoolItem,
        get_unspent_lineage_info_for_puzzle_hash: Callable[[bytes32], Awaitable[Optional[UnspentLineageInfo]]],
        height: uint32,
        constants: ConsensusConstants,
    ) -> None:
        """
        Provides the caller with an in-place internal mempool item that has a
        proper state of fast forwarded coin spends and additions starting from
        the most recent unspent versions of the related singleton spends.

        Args:
            mempool_item: in-out parameter for the internal mempool item to process
            get_unspent_lineage_info_for_puzzle_hash: to lookup the most recent
                version of the singleton from the coin store
            constants: needed in order to refresh the mempool item if needed
            height: needed in order to refresh the mempool item if needed

        Raises:
            If a fast forward cannot proceed, to prevent potential double spends
        """
        new_coin_spends = []
        ff_bundle_coin_spends = {}
        replaced_coin_ids = []
        for coin_id, spend_data in mempool_item.bundle_coin_spends.items():
            if not spend_data.eligible_for_fast_forward:
                # Nothing to do for this spend, moving on
                new_coin_spends.append(spend_data.coin_spend)
                continue

            # NOTE: We need to support finding the most recent version of a singleton
            # both in the DB and in the current state of the block we are
            # building, in case we have already spent the singleton

            # See if we added a fast forward spend with this puzzle hash before
            unspent_lineage_info = self.fast_forward_spends.get(spend_data.coin_spend.coin.puzzle_hash)
            if unspent_lineage_info is None:
                # We didn't, so let's lookup the most recent version from the DB
                unspent_lineage_info = await get_unspent_lineage_info_for_puzzle_hash(
                    spend_data.coin_spend.coin.puzzle_hash
                )
                if unspent_lineage_info is None:
                    raise ValueError("Cannot proceed with singleton spend fast forward.")
                # See if we're the most recent version
                if unspent_lineage_info.coin_id == coin_id:
                    # We are, so we don't need to fast forward, we just need to
                    # set the next version from our additions to chain ff spends
                    set_next_singleton_version(
                        current_singleton=spend_data.coin_spend.coin,
                        singleton_additions=spend_data.additions,
                        fast_forward_spends=self.fast_forward_spends,
                    )
                    # Nothing more to do for this spend, moving on
                    new_coin_spends.append(spend_data.coin_spend)
                    continue
                # We're not the most recent version, so let's fast forward
                new_coin_spend, patched_additions = perform_the_fast_forward(
                    unspent_lineage_info=unspent_lineage_info,
                    spend_data=spend_data,
                    fast_forward_spends=self.fast_forward_spends,
                )
                # Mark this coin for a coin spend data update
                replaced_coin_ids.append(coin_id)
                ff_bundle_coin_spends[new_coin_spend.coin.name()] = BundleCoinSpend(
                    coin_spend=new_coin_spend,
                    eligible_for_dedup=spend_data.eligible_for_dedup,
                    eligible_for_fast_forward=spend_data.eligible_for_fast_forward,
                    additions=patched_additions,
                    cost=spend_data.cost,
                )
                # Update the list of coins spends that will make the new fast
                # forward spend bundle
                new_coin_spends.append(new_coin_spend)
                # We're done here, moving on
                continue
            # We've added a ff spend with this puzzle hash before, so build on that
            # NOTE: As it's not possible to submit a transaction to the mempool that
            # spends the output of another transaction already in the mempool,
            # we don't need to check if we're the most recent version because
            # at this point we cannot be, so we must fast forward
            new_coin_spend, patched_additions = perform_the_fast_forward(
                unspent_lineage_info=unspent_lineage_info,
                spend_data=spend_data,
                fast_forward_spends=self.fast_forward_spends,
            )
            # Mark this coin for a coin spend data update
            replaced_coin_ids.append(coin_id)
            ff_bundle_coin_spends[new_coin_spend.coin.name()] = BundleCoinSpend(
                coin_spend=new_coin_spend,
                eligible_for_dedup=spend_data.eligible_for_dedup,
                eligible_for_fast_forward=spend_data.eligible_for_fast_forward,
                additions=patched_additions,
                cost=spend_data.cost,
            )
            # Update the list of coins spends that make the new fast forward bundle
            new_coin_spends.append(new_coin_spend)
        if len(ff_bundle_coin_spends) == 0:
            # This item doesn't have any fast forward coins, nothing to do here
            return
        # Update the mempool item after validating the new spend bundle
        new_sb = SpendBundle(
            coin_spends=new_coin_spends, aggregated_signature=mempool_item.spend_bundle.aggregated_signature
        )
        # We need to run the new spend bundle to make sure it remains valid
        assert mempool_item.conds is not None
        try:
            new_conditions = get_conditions_from_spendbundle(
                new_sb,
                mempool_item.conds.cost,
                constants,
                height,
            )
        # validate_clvm_and_signature raises a TypeError with an error code
        except TypeError as e:
            # Convert that to a ValidationError
            if len(e.args) > 0:
                error = Err(e.args[0])
                raise ValueError(f"Mempool item became invalid after singleton fast forward with error {error}.")
            else:
                raise ValueError(
                    "Mempool item became invalid after singleton fast forward with an unspecified error."
                )  # pragma: no cover

        # Update bundle_coin_spends using the collected data
        for coin_id in replaced_coin_ids:
            mempool_item.bundle_coin_spends.pop(coin_id, None)
        mempool_item.bundle_coin_spends.update(ff_bundle_coin_spends)
        # Update the mempool item with the new spend bundle related information
        # NOTE: From this point on, in `create_bundle_from_mempool_items`, we rely
        # on `bundle_coin_spends` and we don't use this updated spend bundle
        # information, as we'll only need `aggregated_signature` which doesn't
        # change. Still, it's good form to update the spend bundle with the
        # new coin spends
        mempool_item.spend_bundle = new_sb
        mempool_item.conds = new_conditions
