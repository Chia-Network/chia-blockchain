from __future__ import annotations

from typing import Any

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.cmds.wallet_funcs import print_offer_summary
from chia.wallet.wallet_request_types import CATAssetIDToName, CATAssetIDToNameResponse

TEST_DUCKSAUCE_ASSET_ID = "1000000000000000000000000000000000000000000000000000000000000001"
TEST_CRUNCHBERRIES_ASSET_ID = "1000000000000000000000000000000000000000000000000000000000000002"
TEST_UNICORNTEARS_ASSET_ID = "1000000000000000000000000000000000000000000000000000000000000003"

TEST_ASSET_ID_NAME_MAPPING: dict[bytes32, tuple[uint32, str]] = {
    bytes32.from_hexstr(TEST_DUCKSAUCE_ASSET_ID): (uint32(2), "DuckSauce"),
    bytes32.from_hexstr(TEST_CRUNCHBERRIES_ASSET_ID): (uint32(3), "CrunchBerries"),
    bytes32.from_hexstr(TEST_UNICORNTEARS_ASSET_ID): (uint32(4), "UnicornTears"),
}


async def cat_name_resolver(request: CATAssetIDToName) -> CATAssetIDToNameResponse:
    return CATAssetIDToNameResponse(*TEST_ASSET_ID_NAME_MAPPING.get(request.asset_id, (None, None)))


@pytest.mark.anyio
async def test_print_offer_summary_xch(capsys: Any) -> None:
    summary_dict = {"xch": str(1_000_000_000_000)}

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 1.0 (1000000000000 mojos)" in captured.out


@pytest.mark.anyio
async def test_print_offer_summary_cat(capsys: Any) -> None:
    summary_dict = {
        TEST_DUCKSAUCE_ASSET_ID: str(1_000),
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "DuckSauce (Wallet ID: 2): 1.0 (1000 mojos)" in captured.out


@pytest.mark.anyio
async def test_print_offer_summary_multiple_cats(capsys: Any) -> None:
    summary_dict = {
        TEST_DUCKSAUCE_ASSET_ID: str(1_000),
        TEST_CRUNCHBERRIES_ASSET_ID: str(2_000),
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "DuckSauce (Wallet ID: 2): 1.0 (1000 mojos)" in captured.out
    assert "CrunchBerries (Wallet ID: 3): 2.0 (2000 mojos)" in captured.out


@pytest.mark.anyio
async def test_print_offer_summary_xch_and_cats(capsys: Any) -> None:
    summary_dict = {
        "xch": str(2_500_000_000_000),
        TEST_DUCKSAUCE_ASSET_ID: str(1_111),
        TEST_CRUNCHBERRIES_ASSET_ID: str(2_222),
        TEST_UNICORNTEARS_ASSET_ID: str(3_333),
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 2.5 (2500000000000 mojos)" in captured.out
    assert "DuckSauce (Wallet ID: 2): 1.111 (1111 mojos)" in captured.out
    assert "CrunchBerries (Wallet ID: 3): 2.222 (2222 mojos)" in captured.out
    assert "UnicornTears (Wallet ID: 4): 3.333 (3333 mojos)" in captured.out


@pytest.mark.anyio
async def test_print_offer_summary_xch_and_cats_with_zero_values(capsys: Any) -> None:
    summary_dict = {
        "xch": str(0),
        TEST_DUCKSAUCE_ASSET_ID: str(0),
        TEST_CRUNCHBERRIES_ASSET_ID: str(0),
        TEST_UNICORNTEARS_ASSET_ID: str(0),
    }

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 0.0 (0 mojos)" in captured.out
    assert "DuckSauce (Wallet ID: 2): 0.0 (0 mojos)" in captured.out
    assert "CrunchBerries (Wallet ID: 3): 0.0 (0 mojos)" in captured.out
    assert "UnicornTears (Wallet ID: 4): 0.0 (0 mojos)" in captured.out


@pytest.mark.anyio
async def test_print_offer_summary_cat_with_fee_and_change(capsys: Any) -> None:
    summary_dict = {
        TEST_DUCKSAUCE_ASSET_ID: str(1_000),
        "unknown": str(3_456),
    }

    await print_offer_summary(cat_name_resolver, summary_dict, has_fee=True)

    captured = capsys.readouterr()

    assert "DuckSauce (Wallet ID: 2): 1.0 (1000 mojos)" in captured.out
    assert "Unknown: 3456 mojos  [Typically represents change returned from the included fee]" in captured.out


@pytest.mark.anyio
async def test_print_offer_summary_xch_with_one_mojo(capsys: Any) -> None:
    summary_dict = {"xch": str(1)}

    await print_offer_summary(cat_name_resolver, summary_dict)

    captured = capsys.readouterr()

    assert "XCH (Wallet ID: 1): 1e-12 (1 mojo)" in captured.out
