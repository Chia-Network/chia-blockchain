from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pytest
from blspy import G2Element
from chia_rs import Coin

from chia.clvm.spend_sim import SimClient, SpendSim
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bitcoin_fee_estimator import BitcoinFeeEstimator
from chia.full_node.fee_tracker import FeeStat
from chia.full_node.mempool_manager import MempoolManager
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.clvm_cost import CLVMCost
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.types.mojos import Mojos
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint64

log = logging.getLogger(__name__)

the_puzzle_hash = bytes32(
    bytes.fromhex("9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2")
)  # Program.to(1)


@dataclass(frozen=True)
class CoinPair:
    coin: Coin
    fee_coin: Coin


async def farm(
    sim: SpendSim,
    puzzle_hash: bytes32,
    item_inclusion_filter: Optional[Callable[[MempoolManager, MempoolItem], bool]] = None,
) -> Tuple[List[Coin], List[Coin], List[Coin]]:
    additions, removals = await sim.farm_block(puzzle_hash)  # , item_inclusion_filter)
    height = sim.get_height()
    new_reward_coins = sim.block_records[height].reward_claims_incorporated
    return additions, removals, new_reward_coins


def make_tx_sb(from_coin: Coin) -> SpendBundle:
    coin_spend = CoinSpend(
        from_coin,
        Program.to(1),
        Program.to([[51, from_coin.puzzle_hash, from_coin.amount]]),
    )
    spend_bundle = SpendBundle([coin_spend], G2Element())
    return spend_bundle


async def select_fee_coin(sim_client: SimClient, avoid_coins: List[Coin], puzzle_hash: bytes32, fee: int) -> Coin:
    assert fee >= 0
    spendable_coins: List[CoinRecord] = await sim_client.get_coin_records_by_puzzle_hash(puzzle_hash)
    for cr in spendable_coins:
        if cr.coin in avoid_coins:
            continue
        if cr.coin.amount >= fee:
            return cr.coin
    raise RuntimeError(f"No spendable coin has enough value to add a fee of {fee}")


def add_fee(sb: SpendBundle, fee: int, fee_coin: Coin, recv_puzzle_hash: bytes32) -> Tuple[SpendBundle, Coin]:
    fee_sb = SpendBundle(
        [
            CoinSpend(
                fee_coin,
                Program.to(1),
                Program.to([[51, recv_puzzle_hash, fee_coin.amount - fee]]),
            )
        ],
        G2Element(),
    )
    change_coin = Coin(fee_coin.name(), recv_puzzle_hash, fee_coin.amount - fee)
    return SpendBundle.aggregate([sb, fee_sb]), change_coin


async def transfer_coins(
    sim: SpendSim,
    sim_client: SimClient,
    input_pairs: Set[CoinPair],
    phs: List[bytes32],
    fees: List[uint64],
    fee_change_ph: bytes32,
    item_inclusion_filter: Optional[Callable[[MempoolManager, MempoolItem], bool]],
) -> Tuple[Set[CoinPair], Set[CoinPair]]:
    """
    Returns Tuple(new_spend_coins, new_fee_coins)
    """
    assert len(input_pairs) == len(fees)

    if any([v < 0 for v in fees]):
        raise ValueError("fees members must not be negative")
    tx_push_count = 0
    mempool_conflicts = set()
    double_spends = set()
    for input_pair, ph, fee in zip(input_pairs, phs, fees):
        from_coin = input_pair.coin
        fee_coin = input_pair.fee_coin
        spend_bundle: SpendBundle = make_tx_sb(from_coin)
        assert spend_bundle.additions()[0].amount == spend_bundle.removals()[0].amount

        assert fee <= fee_coin.amount
        sb_with_fee, change_coin = add_fee(spend_bundle, fee, fee_coin, fee_change_ph)
        assert sb_with_fee.fees() == fee

        try:
            await sim_client.service.mempool_manager.pre_validate_spendbundle(sb_with_fee, None, sb_with_fee.name())
        except ValidationError as e:
            if len(e.args) > 0 and e.args[0] == Err.BLOCK_COST_EXCEEDS_MAX:
                log.warning("Block full")
                break
        status, err = await sim_client.push_tx(sb_with_fee)
        tx_push_count += 1
        if err:
            log.error(err)
            if err == Err.MEMPOOL_CONFLICT:
                mempool_conflicts.add(input_pair)
                continue
            if err == Err.DOUBLE_SPEND:
                double_spends.add(input_pair)
                continue
            log.error(input_pairs)
            sb_with_fee.debug()  # type: ignore
            raise RuntimeError(err)

    additions, removals_list, new_reward_coins = await farm(
        sim, puzzle_hash=the_puzzle_hash, item_inclusion_filter=item_inclusion_filter
    )

    removals = set(removals_list)
    spent_coins = set([p.coin for p in input_pairs]) & removals
    spent_fee_coins = set([p.fee_coin for p in input_pairs]) & removals

    new_coin_records = await sim_client.get_coin_records_by_parent_ids([c.name() for c in spent_coins])
    new_fee_records = await sim_client.get_coin_records_by_parent_ids([f.name() for f in spent_fee_coins])
    assert len(new_coin_records) == len(new_fee_records)

    new_pairs = set([CoinPair(c.coin, f.coin) for c, f in zip(new_coin_records, new_fee_records)])

    for p in new_pairs:
        assert p.coin in additions
        assert p.fee_coin in additions

    unspent_pairs = set()
    for p in input_pairs:
        fee_removed = p.fee_coin in removals
        coin_removed = p.coin in removals
        assert (fee_removed and coin_removed) or ((not fee_removed) and (not coin_removed))
        if p.coin not in removals:
            unspent_pairs.add(p)

    return (unspent_pairs, new_pairs)


async def init_test(
    puzzle_hash: bytes32, spends_per_block: int, *, constants: Optional[Dict[str, Any]]
) -> Tuple[SpendSim, SimClient, BitcoinFeeEstimator, Set[CoinPair]]:
    defaults: ConsensusConstants = DEFAULT_CONSTANTS
    assert constants
    sim = await SpendSim.create(
        defaults=defaults.replace(
            MAX_BLOCK_COST_CLVM=constants["MAX_BLOCK_COST_CLVM"], MEMPOOL_BLOCK_BUFFER=constants["MEMPOOL_BLOCK_BUFFER"]
        )
    )

    cli = SimClient(sim)
    new_reward_coins = []
    spend_coins = []
    fee_coins = []
    await farm(sim, puzzle_hash)

    for i in range(1, spends_per_block + 1):
        await farm(sim, puzzle_hash)
        new_reward_coins.extend(sim.block_records[i].reward_claims_incorporated)
        fee_coins.append(sim.block_records[i].reward_claims_incorporated[0])
        spend_coins.append(sim.block_records[i].reward_claims_incorporated[1])
    await farm(sim, puzzle_hash)

    assert len(sim.blocks) == spends_per_block + 2
    assert sim.blocks[-1].height == spends_per_block + 1
    assert sim.block_records[0].reward_claims_incorporated[0].amount == 18375000000000000000
    assert sim.block_records[0].reward_claims_incorporated[1].amount == 2625000000000000000

    assert sim.block_records[1].reward_claims_incorporated[0].amount == 1750000000000
    assert sim.block_records[1].reward_claims_incorporated[1].amount == 250000000000

    estimator: BitcoinFeeEstimator = sim.mempool_manager.mempool.fee_estimator  # type:ignore
    coin_pairs = [CoinPair(c, f) for c, f in zip(spend_coins, fee_coins)]
    return sim, cli, estimator, set(coin_pairs)


@pytest.mark.asyncio
async def test_static_fee_rate() -> None:
    """
    Test if the fee estimator converges to a set prediction after a certain number
    of full blocks with a set average fee rate.
    """

    typical_cost = 2 * 5900283  # Cost for a typical main wallet spend
    fee = uint64(typical_cost * 2)
    num_coins_per_block = 2
    num_rounds = 30
    sim = None

    def always(mm: MempoolManager, mi: MempoolItem) -> bool:
        return True

    def wait_5_blocks(mm: MempoolManager, mi: MempoolItem) -> bool:
        assert mm.peak
        return mm.peak.height >= mi.height_added_to_mempool + 5

    try:
        height = 0
        max_block_cost = int(typical_cost * 1.5)
        constants = {"MAX_BLOCK_COST_CLVM": max_block_cost, "MEMPOOL_BLOCK_BUFFER": 1}
        sim, cli, estimator, spend_pairs = await init_test(the_puzzle_hash, num_coins_per_block, constants=constants)
        phs = [the_puzzle_hash for _ in range(num_coins_per_block)]
        # coin_values = [x + 1 for x in range(num_coins)]

        for step in range(1, 1 + num_rounds):
            height = sim.get_height()

            tx_fees = [fee for _ in spend_pairs]
            new_unspent_pairs, new_pairs = await transfer_coins(
                sim, cli, spend_pairs, phs, tx_fees, the_puzzle_hash, wait_5_blocks
            )

            # remove new_unspent_coins from new_spend_coins
            assert len(new_unspent_pairs) + len(new_pairs) == len(spend_pairs)

            log.warning(f"step {step} DELTA: new_spend_coins={len(new_pairs)}, new_unspent={len(new_unspent_pairs)}")

            spend_pairs = new_pairs | new_unspent_pairs
            unspent_pairs = new_unspent_pairs

            log.warning(f"step {step} STATE:     spend_coins={len(spend_pairs)},     unspent={len(unspent_pairs)}")

            log.warning(f"mempool size: {len(sim.mempool_manager.mempool.spends)}")
            log.warning(f"{sim.mempool_manager.mempool.spends.keys()}")
            log.warning(f"{sim.mempool_manager.mempool.spends.values()}")
            fees_in_mempool = 0
            for m in sim.mempool_manager.mempool.spends.values():
                fees_in_mempool += m.spend_bundle.fees()
            log.warning(f"fees_in_mempool={fees_in_mempool}")

        log.warning(estimator.get_tracker().short_horizon.max_confirms)
        log.warning(estimator.get_tracker().short_horizon.max_periods)

        rate = FeeRate.create(Mojos(fee), CLVMCost(uint64(typical_cost)))
        est = estimator.estimate_fee_rate(time_offset_seconds=240)
        log.warning(f"height: {height}  estimate: {est}  rate: {rate}")
        fee_stats: FeeStat = estimator.get_tracker().short_horizon
        log.warning(fee_stats)
        assert est.mojos_per_clvm_cost > rate.mojos_per_clvm_cost

    finally:
        if sim:
            await sim.close()
