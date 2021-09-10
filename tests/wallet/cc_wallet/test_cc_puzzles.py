from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.util.ints import uint64
from chia.wallet.puzzles.cc_loader import CC_MOD
from chia.wallet.puzzles.everything_with_signature import create_genesis_sig_checker
from chia.wallet.cc_wallet.cc_utils import cc_puzzle_for_inner_puzzle


def test_signature_genesis():
    pubkey = Program.to(0x00FADEDDAB)
    genesis_checker = create_genesis_sig_checker(pubkey)
    innerpuz = Program.to([1, [51, 0x00CAFEF00D, 200]])
    puzzle = cc_puzzle_for_inner_puzzle(CC_MOD, genesis_checker, innerpuz)

    # coin = Coin(puzzle.get_tree_hash(), puzzle.get_tree_hash(), uint64(200))

    # lineage proof is  (0 . some_opaque_proof_passed_to_GENESIS_COIN_CHECKER)
    lineage_proof = (0, 0)

    my_coin_bundle = (
        [puzzle.get_tree_hash(), puzzle.get_tree_hash(), uint64(200), innerpuz.get_tree_hash()],
        lineage_proof,
    )
    solution = Program.to([0, my_coin_bundle, my_coin_bundle, my_coin_bundle, 0, 0])
    result = puzzle.run_with_cost(INFINITE_COST, solution)

    assert result[1].rest().first().first().as_int() == 50
    assert result[1].rest().first().rest().first().as_int() == 0x00FADEDDAB
