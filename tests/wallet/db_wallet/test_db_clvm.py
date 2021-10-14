import pytest
from chia.wallet.db_wallet.db_wallet_puzzles import create_host_fullpuz, create_offer_fullpuz, SINGLETON_LAUNCHER
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32


def test_create_db_report():
    innerpuz: Program = Program.to(1)  # (x)
    current_root: bytes32 = innerpuz.get_tree_hash()  # just need a bytes32
    genesis_id: bytes32 = Coin(current_root, SINGLETON_LAUNCHER.get_tree_hash(), 201).name()  # see above
    full_puz = create_host_fullpuz(innerpuz, current_root, genesis_id)
    assert full_puz is not None
    # spend_type
    # my_puzhash
    # my_amount
    # inner_solution
    db_solution = Program.to([1, full_puz.get_tree_hash(), 201, 0])
    # lineage_proof my_amount inner_solution
    launcher_amount = 201
    lineage_proof = Program.to([current_root, launcher_amount])
    full_solution = Program.to([lineage_proof, 201, db_solution])

    cost, result = full_puz.run_with_cost(INFINITE_COST, full_solution)
    assert len(result.as_python()) == 5
