from typing import Dict, List
from chia.rpc.cat_utils import convert_to_coin
from chia.rpc.utils import get_coin_records_map
from chia.types.coin_record import CoinRecord


def get_test_coin_record(amount: int) -> CoinRecord:
    return CoinRecord(
        coin=convert_to_coin(
            raw_coin={
                "amount": amount,
                "parent_coin_info": "0x8599cc835a767775c655025fcd4249170d37affc4f4a85c830d8a41a93c1ea37",
                "puzzle_hash": "0xa0557e2022d2d4803ad6b3638a909118d18ad8ccbecc844557b34f268f78938a",
            }
        ),
        confirmed_block_index=1,
        spent_block_index=2,
        coinbase=False,
        timestamp=432423,
    )


def get_test_coin_records(amounts: List[int]) -> List[CoinRecord]:
    res = []
    for amount in amounts:
        res.append(get_test_coin_record(amount=amount))
    return res


def test_convert_to_parent_coin_spends() -> None:
    amounts = [32, 5435, 5436, 786876]
    res: Dict[str, CoinRecord] = get_coin_records_map(
        coin_records=get_test_coin_records(amounts=amounts),
    )
    assert res is not None
    assert len(res) == len(amounts)
    for name in res:
        print(f"test_convert_to_parent_coin_spends: {name}")
        coin_record = res[name]
        assert name == "0x" + coin_record.name.hex()


test_convert_to_parent_coin_spends()
