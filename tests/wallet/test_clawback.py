from blspy import G1Element
from secrets import token_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_puzzles import NFT_METADATA_UPDATER, create_full_puzzle
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions, puzzle_for_pk
from clvm.casts import int_to_bytes

from chia.wallet.puzzles.clawback import (
    create_clawback_puzzle,
    create_sender_solution,
    create_p2_puzzle_hash_puzzle,
    create_augmented_cond_puzzle,
    create_clawback_merkle_tree,
)

ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()

def test_clawback_puzzles():
    timelock = 60
    amount = 1000
    pk = G1Element()
    sender_puz = puzzle_for_pk(pk)
    sender_ph = sender_puz.get_tree_hash()
    recipient_puz = ACS
    recipient_ph = ACS_PH

    clawback_puz = create_clawback_puzzle(timelock, sender_ph, recipient_ph)

    sender_sol = solution_for_conditions(
        [
         [51, sender_ph, amount],
        ]
    )

    merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
    cb_sender_sol = create_sender_solution(timelock, sender_ph, recipient_ph, sender_puz, sender_sol)

    conds = clawback_puz.run(cb_sender_sol)
    assert conds

    recipient_sol = Program.to([[51, recipient_ph, amount]])
    cb_recipient_sol = create_sender_solution(timelock, sender_ph, recipient_ph, recipient_puz, recipient_sol)
    conds = clawback_puz.run(cb_recipient_sol)
    assert conds
