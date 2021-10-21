from chia.wallet.db_wallet.db_wallet_puzzles import (
    create_host_fullpuz,
    create_offer_fullpuz,
    SINGLETON_LAUNCHER,
    create_host_layer_puzzle,
)
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.announcement import Announcement
from chia.wallet.util.merkle_tree import MerkleTree


def test_create_db_report():
    innerpuz: Program = Program.to(1)
    nodes = [innerpuz.get_tree_hash(), Program.to([8]).get_tree_hash()]
    current_tree = MerkleTree(nodes)
    current_root: bytes32 = current_tree.calculate_root()  # just need a bytes32
    genesis_id: bytes32 = Coin(current_root, SINGLETON_LAUNCHER.get_tree_hash(), 201).name()  # see above
    full_puz = create_host_fullpuz(innerpuz, current_root, genesis_id)
    assert full_puz is not None
    db_solution = Program.to([1, (full_puz.get_tree_hash(), 201)])
    # lineage_proof my_amount inner_solution
    launcher_amount = 201
    lineage_proof = Program.to([current_root, launcher_amount])
    full_solution = Program.to([lineage_proof, 201, db_solution])

    cost, result = full_puz.run_with_cost(INFINITE_COST, full_solution)
    assert len(result.as_python()) == 5
    assert result.as_python()[1][1] == current_root


def test_create_db_update():
    innerpuz: Program = Program.to(1)
    nodes = [innerpuz.get_tree_hash(), Program.to([8]).get_tree_hash()]
    current_tree = MerkleTree(nodes)
    current_root: bytes32 = current_tree.calculate_root()  # just need a bytes32
    genesis_id: bytes32 = Coin(current_root, SINGLETON_LAUNCHER.get_tree_hash(), 201).name()  # see above
    full_puz = create_host_fullpuz(innerpuz, current_root, genesis_id)
    assert full_puz is not None
    nodes.append(Program.to("blah").get_tree_hash())
    new_tree = MerkleTree(nodes)
    new_root = new_tree.calculate_root()
    host_puz = create_host_layer_puzzle(innerpuz, new_root)
    inner_solution = Program.to([[51, host_puz.get_tree_hash(), 201]])
    db_solution = Program.to([0, inner_solution])
    # lineage_proof my_amount inner_solution
    launcher_amount = 201
    lineage_proof = Program.to([current_root, launcher_amount])
    full_solution = Program.to([lineage_proof, 201, db_solution])
    full_puz = create_host_fullpuz(innerpuz, new_root, genesis_id)
    cost, result = full_puz.run_with_cost(INFINITE_COST, full_solution)

    assert len(result.as_python()) == 2
    assert result.as_python()[1][1] == full_puz.get_tree_hash()


def test_valid_offer_claim():
    innerpuz: Program = Program.to(1)
    nodes = [innerpuz.get_tree_hash(), Program.to([8]).get_tree_hash()]
    current_tree = MerkleTree(nodes)
    current_root: bytes32 = current_tree.calculate_root()  # just need a bytes32
    genesis_id: bytes32 = Coin(current_root, SINGLETON_LAUNCHER.get_tree_hash(), 201).name()  # see above
    full_puz = create_host_fullpuz(innerpuz, current_root, genesis_id)
    assert full_puz is not None

    recovery_target = Program.to("recovery").get_tree_hash()
    claim_target = Program.to("claim").get_tree_hash()
    offer_puz = create_offer_fullpuz(innerpuz.get_tree_hash(), genesis_id, claim_target, recovery_target, 1000)

    leaf = innerpuz.get_tree_hash()
    inclusion_proof = current_tree.generate_proof(leaf)
    expected_announcement = Announcement(full_puz.get_tree_hash(), current_root)
    cost, result = offer_puz.run_with_cost(INFINITE_COST, Program.to([1, 201, leaf, current_root, inclusion_proof]))
    assert result.as_python()[2][1] == expected_announcement.name()


def test_bad_info_and_recover():
    innerpuz: Program = Program.to(1)
    nodes = [innerpuz.get_tree_hash(), Program.to([8]).get_tree_hash()]
    current_tree = MerkleTree(nodes)
    current_root: bytes32 = current_tree.calculate_root()  # just need a bytes32
    genesis_id: bytes32 = Coin(current_root, SINGLETON_LAUNCHER.get_tree_hash(), 201).name()  # see above
    full_puz = create_host_fullpuz(innerpuz, current_root, genesis_id)
    assert full_puz is not None

    recovery_target = Program.to("recovery").get_tree_hash()
    claim_target = Program.to("claim").get_tree_hash()
    timelock = 1000
    offer_puz = create_offer_fullpuz(innerpuz.get_tree_hash(), genesis_id, claim_target, recovery_target, timelock)

    leaf = Program.to("wrong").get_tree_hash()
    inclusion_proof = current_tree.generate_proof(leaf)
    try:
        cost, result = offer_puz.run_with_cost(INFINITE_COST, Program.to([1, 201, leaf, current_root, inclusion_proof]))
    except Exception:
        print()
    else:
        assert False
    cost, result = offer_puz.run_with_cost(INFINITE_COST, Program.to([0, 201]))
    assert result.as_python()[0][1] == recovery_target
    assert result.rest().rest().first().rest().first().as_int() == timelock
