from __future__ import annotations

import pytest


@pytest.fixture(scope="function", autouse=True)
async def _use_wallet_block_tools(ignore_block_validation: None) -> None:
    """Use simplified block creation (WalletBlockTools) for faster tests."""
