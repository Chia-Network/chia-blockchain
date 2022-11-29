from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pytest

from chia.cmds.wallet_funcs import print_offer_summary
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32

TEST_DUCKSAUCE_ASSET_ID = "1000000000000000000000000000000000000000000000000000000000000001"
TEST_CRUNCHBERRIES_ASSET_ID = "1000000000000000000000000000000000000000000000000000000000000002"
TEST_UNICORNTEARS_ASSET_ID = "1000000000000000000000000000000000000000000000000000000000000003"

TEST_ASSET_ID_NAME_MAPPING: Dict[bytes32, Tuple[uint32, str]] = {
    bytes32.from_hexstr(TEST_DUCKSAUCE_ASSET_ID): (uint32(2), "DuckSauce"),
    bytes32.from_hexstr(TEST_CRUNCHBERRIES_ASSET_ID): (uint32(3), "CrunchBerries"),
    bytes32.from_hexstr(TEST_UNICORNTEARS_ASSET_ID): (uint32(4), "UnicornTears"),
}


async def cat_name_resolver(asset_id: bytes32) -> Optional[Tuple[Optional[uint32], str]]:
    return TEST_ASSET_ID_NAME_MAPPING.get(asset_id)


@pytest.mark.asyncio
async def test_print_offer_summary_xch(capsys: Any) -> None:
    summary_dict = {"xch": 1_000_000_000_000}

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 1.0 (1000000000000 mojos)" in captured.out


@pytest.mark.asyncio
async def test_print_offer_summary_cat(capsys: Any) -> None:
    summary_dict = {
        TEST_DUCKSAUCE_ASSET_ID: 1_000,
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "DuckSauce (Wallet ID: 2): 1.0 (1000 mojos)" in captured.out


@pytest.mark.asyncio
async def test_print_offer_summary_multiple_cats(capsys: Any) -> None:
    summary_dict = {
        TEST_DUCKSAUCE_ASSET_ID: 1_000,
        TEST_CRUNCHBERRIES_ASSET_ID: 2_000,
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "DuckSauce (Wallet ID: 2): 1.0 (1000 mojos)" in captured.out
    assert "CrunchBerries (Wallet ID: 3): 2.0 (2000 mojos)" in captured.out


@pytest.mark.asyncio
async def test_print_offer_summary_xch_and_cats(capsys: Any) -> None:
    summary_dict = {
        "xch": 2_500_000_000_000,
        TEST_DUCKSAUCE_ASSET_ID: 1_111,
        TEST_CRUNCHBERRIES_ASSET_ID: 2_222,
        TEST_UNICORNTEARS_ASSET_ID: 3_333,
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 2.5 (2500000000000 mojos)" in captured.out
    assert "DuckSauce (Wallet ID: 2): 1.111 (1111 mojos)" in captured.out
    assert "CrunchBerries (Wallet ID: 3): 2.222 (2222 mojos)" in captured.out
    assert "UnicornTears (Wallet ID: 4): 3.333 (3333 mojos)" in captured.out


@pytest.mark.asyncio
async def test_print_offer_summary_xch_and_cats_with_zero_values(capsys: Any) -> None:
    summary_dict = {
        "xch": 0,
        TEST_DUCKSAUCE_ASSET_ID: 0,
        TEST_CRUNCHBERRIES_ASSET_ID: 0,
        TEST_UNICORNTEARS_ASSET_ID: 0,
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 0.0 (0 mojos)" in captured.out
    assert "DuckSauce (Wallet ID: 2): 0.0 (0 mojos)" in captured.out
    assert "CrunchBerries (Wallet ID: 3): 0.0 (0 mojos)" in captured.out
    assert "UnicornTears (Wallet ID: 4): 0.0 (0 mojos)" in captured.out


@pytest.mark.asyncio
async def test_print_offer_summary_cat_with_fee_and_change(capsys: Any) -> None:
    summary_dict = {
        TEST_DUCKSAUCE_ASSET_ID: 1_000,
        "unknown": 3_456,
    }

    await print_offer_summary(cat_name_resolver, summary_dict, has_fee=True)

    captured = capsys.readouterr()

    assert "DuckSauce (Wallet ID: 2): 1.0 (1000 mojos)" in captured.out
    assert "Unknown: 3456 mojos  [Typically represents change returned from the included fee]" in captured.out


@pytest.mark.asyncio
async def test_print_offer_summary_xch_with_one_mojo(capsys: Any) -> None:
    summary_dict = {"xch": 1}

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 1e-12 (1 mojo)" in captured.out
