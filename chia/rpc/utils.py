from typing import Dict, List

from chia.types.coin_record import CoinRecord


def get_coin_records_map(coin_records: List[CoinRecord]) -> Dict[str, CoinRecord]:
    res = {}
    for coin_record in coin_records:
        res["0x" + coin_record.name.hex()] = coin_record
    return res
