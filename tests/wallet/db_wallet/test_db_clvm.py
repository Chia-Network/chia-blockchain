import pytest
from chia.wallet.db_wallet.db_wallet_puzzles import create_fullpuz
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32


def test_create_db_fullpuz():
    innerpuz: Program = Program.to([8])  # (x)
    current_root: bytes32 = innerpuz.get_tree_hash()  # just need a bytes32
    genesis_id: bytes32 = current_root  # see above
    full_puz = create_fullpuz(innerpuz, current_root, genesis_id)
    assert full_puz is not None
