from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Dict, Iterator, Optional, Set

from chia.full_node.mempool_check_conditions import mempool_check_conditions_dict  # noqa
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import (
    conditions_dict_for_solution,
    coin_announcement_names_for_conditions_dict,
    puzzle_announcement_names_for_conditions_dict,
)
from chia.util.ints import uint32, uint64


MAX_COST = 11000000000


class BadSpendBundleError(Exception):
    pass


@dataclass
class CoinTimestamp:
    seconds: int
    height: int


class CoinStore:
    def __init__(self, reward_mask: int = 0):
        self._db: Dict[bytes32, CoinRecord] = dict()
        self._ph_index: Dict = defaultdict(list)
        self._reward_mask = reward_mask

    def farm_coin(
        self,
        puzzle_hash: bytes32,
        birthday: CoinTimestamp,
        amount: int = 1024,
        prefix=bytes32.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000000000"),  # noqa
    ) -> Coin:
        parent = bytes32(
            [
                a | b
                for a, b in zip(
                    prefix,
                    birthday.height.to_bytes(32, "big"),
                )
            ],
        )
        # parent = birthday.height.to_bytes(32, "big")
        coin = Coin(parent, puzzle_hash, uint64(amount))
        self._add_coin_entry(coin, birthday)
        return coin

    def validate_spend_bundle(
        self,
        spend_bundle: SpendBundle,
        now: CoinTimestamp,
        max_cost: int,
    ) -> int:
        # this should use blockchain consensus code

        coin_announcements: Set[bytes32] = set()
        puzzle_announcements: Set[bytes32] = set()

        conditions_dicts = []
        for coin_solution in spend_bundle.coin_solutions:
            assert isinstance(coin_solution.coin, Coin)
            err, conditions_dict, cost = conditions_dict_for_solution(
                coin_solution.puzzle_reveal, coin_solution.solution, max_cost
            )
            if conditions_dict is None:
                raise BadSpendBundleError(f"clvm validation failure {err}")
            conditions_dicts.append(conditions_dict)
            coin_announcements.update(
                coin_announcement_names_for_conditions_dict(
                    conditions_dict,
                    coin_solution.coin,
                )
            )
            puzzle_announcements.update(
                puzzle_announcement_names_for_conditions_dict(
                    conditions_dict,
                    coin_solution.coin,
                )
            )

        ephemeral_db = dict(self._db)
        for coin in spend_bundle.additions():
            name = coin.name()
            ephemeral_db[name] = CoinRecord(
                coin,
                uint32(now.height),
                uint32(0),
                False,
                False,
                uint64(now.seconds),
            )

        for coin_solution, conditions_dict in zip(spend_bundle.coin_solutions, conditions_dicts):  # noqa
            prev_transaction_block_height = now.height
            timestamp = now.seconds
            coin_record = ephemeral_db.get(coin_solution.coin.name())
            if coin_record is None:
                raise BadSpendBundleError(f"coin not found for id 0x{coin_solution.coin.name().hex()}")  # noqa
            err = mempool_check_conditions_dict(
                coin_record,
                coin_announcements,
                puzzle_announcements,
                conditions_dict,
                uint32(prev_transaction_block_height),
                uint64(timestamp),
            )
        if err is not None:
            raise BadSpendBundleError(f"condition validation failure {err}")

        return 0

    def update_coin_store_for_spend_bundle(
        self,
        spend_bundle: SpendBundle,
        now: CoinTimestamp,
        max_cost: int,
    ):
        err = self.validate_spend_bundle(spend_bundle, now, max_cost)
        if err != 0:
            raise BadSpendBundleError(f"validation failure {err}")
        additions = spend_bundle.additions()
        removals = spend_bundle.removals()
        for new_coin in additions:
            self._add_coin_entry(new_coin, now)
        for spent_coin in removals:
            coin_name = spent_coin.name()
            coin_record = self._db[coin_name]
            self._db[coin_name] = replace(coin_record, spent_block_index=now.height, spent=True)
        return additions, spend_bundle.coin_solutions

    def coins_for_puzzle_hash(self, puzzle_hash: bytes32) -> Iterator[Coin]:
        for coin_name in self._ph_index[puzzle_hash]:
            coin_entry = self._db[coin_name]
            assert coin_entry.coin.puzzle_hash == puzzle_hash
            yield coin_entry.coin

    def all_coins(self) -> Iterator[Coin]:
        for coin_entry in self._db.values():
            yield coin_entry.coin

    def all_unspent_coins(self) -> Iterator[Coin]:
        for coin_entry in self._db.values():
            if not coin_entry.spent:
                yield coin_entry.coin

    def _add_coin_entry(self, coin: Coin, birthday: CoinTimestamp) -> None:
        name = coin.name()
        # assert name not in self._db
        self._db[name] = CoinRecord(
            coin,
            uint32(birthday.height),
            uint32(0),
            False,
            False,
            uint64(birthday.seconds),
        )
        self._ph_index[coin.puzzle_hash].append(name)

    def coin_record(self, coin_id: bytes32) -> Optional[CoinRecord]:
        return self._db.get(coin_id)
