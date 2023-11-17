from __future__ import annotations

from pathlib import Path

from chia_rs import PrivateKey

from chia.simulator.block_tools import BlockTools
from chia.simulator.derivation_cache import DerivationCacheKey, load_derivation_cache
from chia.wallet.derive_keys import master_sk_to_backup_sk

sk1 = PrivateKey.from_bytes(bytes.fromhex("11d23969c2144bec1dd232d3994427ea5a9756c491636a44ec76c9b9153e4623"))
derived1 = PrivateKey.from_bytes(bytes.fromhex("12e028ed09b9b6fe195b9c6cee4f2d25aae50e02ce23b5e1b2fa4dc7fdf8480c"))

cache = {DerivationCacheKey(sk1, 12381, True): derived1}


def test_derivation_cache_load_fail() -> None:
    """ "Check that tests can work without derivation cache"""
    c1 = load_derivation_cache(Path("/tmp/invalid"))
    backup1 = master_sk_to_backup_sk(sk1)
    print(c1, backup1)


def test_a() -> None:
    """Check that derivations are same with or without cache"""
    backup1 = master_sk_to_backup_sk(sk1)
    backup2 = master_sk_to_backup_sk(sk1, {})
    backup3 = master_sk_to_backup_sk(sk1, cache)
    assert backup1 == backup2
    assert backup2 == backup3


def test_bt_get_farmer_wallet_tool(bt: BlockTools) -> None:
    farmer_wallet_tool = bt.get_farmer_wallet_tool()
    print(farmer_wallet_tool)
