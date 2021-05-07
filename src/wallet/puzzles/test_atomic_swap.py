from blspy import G1Element

from src.util.hash import std_hash

from src.types.condition_opcodes import ConditionOpcode
from src.types.blockchain_format.program import Program

from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    puzzle_for_pk,
    solution_for_delegated_puzzle,
    solution_for_hidden_puzzle,
    calculate_synthetic_public_key,
)
from src.wallet.puzzles.atomic_swap import (
    get_standard_puzzle_with_safe,
    get_safe_transaction_puzzle_hash,
    generate_safe_puzzle,
    generate_safe_solution,
)

from tests.util.key_tool import KeyTool
from tests.clvm.test_puzzles import public_key_for_index


def test_coop_case():
    arbitrary_amount = 50
    key_store = KeyTool()

    # Illustration of how protocol works in ideal scenario
    # 1) "Target" sends pubkey to source
    target_pubkey = G1Element.from_bytes(public_key_for_index(0, key_store))

    # 2) "Source" builds standard atomic swap and publishes their spend
    source_pubkey = G1Element.from_bytes(public_key_for_index(1, key_store))
    preimage = "preimage"
    preimage_hash = std_hash(bytes(preimage, "utf-8"))
    source_claim_time = 1000
    source_built_puzzle = get_standard_puzzle_with_safe(source_pubkey, target_pubkey, source_claim_time, preimage_hash)

    # 3) Target verifies that a coin with the above info is on the blockchain and creates a mirror transaction
    source_built_hidden_puzzle_hash = get_safe_transaction_puzzle_hash(
        source_pubkey, target_pubkey, source_claim_time, preimage_hash
    )
    target_claim_time = 500
    target_built_puzzle = get_standard_puzzle_with_safe(target_pubkey, source_pubkey, target_claim_time, preimage_hash)

    # 4) Source verifies that a coin with the above info is on the blockchain
    target_built_hidden_puzzle_hash = get_safe_transaction_puzzle_hash(
        target_pubkey, source_pubkey, target_claim_time, preimage_hash
    )

    # 5) Both parties FIRST sign the target -> source transaction and spend it
    pay_to_source_puzzle_hash = puzzle_for_pk(source_pubkey).get_tree_hash()
    create_coin_delegated_puzzle = Program.to(
        (1, [[ConditionOpcode.CREATE_COIN, pay_to_source_puzzle_hash, arbitrary_amount]])
    )
    cost, pay_to_source_result = target_built_puzzle.run_with_cost(
        solution_for_delegated_puzzle(create_coin_delegated_puzzle, Program.to(0))
    )
    expected_pay_to_source_result = Program.to(
        [
            [
                ConditionOpcode.AGG_SIG_ME,
                calculate_synthetic_public_key((source_pubkey + target_pubkey), target_built_hidden_puzzle_hash),
                create_coin_delegated_puzzle.get_tree_hash(),
            ],
            [ConditionOpcode.CREATE_COIN, pay_to_source_puzzle_hash, arbitrary_amount],
        ]
    )
    assert pay_to_source_result == expected_pay_to_source_result
    # 6) Both parties THEN sign the source -> target transaction ans spend it
    pay_to_target_puzzle_hash = puzzle_for_pk(target_pubkey).get_tree_hash()
    create_coin_delegated_puzzle = Program.to(
        (1, [[ConditionOpcode.CREATE_COIN, pay_to_target_puzzle_hash, arbitrary_amount]])
    )
    cost, pay_to_target_result = source_built_puzzle.run_with_cost(
        solution_for_delegated_puzzle(create_coin_delegated_puzzle, Program.to(0))
    )
    expected_pay_to_target_result = Program.to(
        [
            [
                ConditionOpcode.AGG_SIG_ME,
                calculate_synthetic_public_key((source_pubkey + target_pubkey), source_built_hidden_puzzle_hash),
                create_coin_delegated_puzzle.get_tree_hash(),
            ],
            [ConditionOpcode.CREATE_COIN, pay_to_target_puzzle_hash, arbitrary_amount],
        ]
    )
    assert pay_to_target_result == expected_pay_to_target_result


# When cooperation has failed and you need to claim coins back
def test_claim_with_signature():
    arbitrary_amount = 50
    key_store = KeyTool()

    # Illustration of how protocol works in disappear scenario
    # 1) "Target" sends pubkey to source
    target_pubkey = G1Element.from_bytes(public_key_for_index(0, key_store))

    # 2) "Source" builds standard atomic swap and publishes their spend
    source_pubkey = G1Element.from_bytes(public_key_for_index(1, key_store))
    preimage = "preimage"
    preimage_hash = std_hash(bytes(preimage, "utf-8"))
    source_claim_time = 1000
    source_built_puzzle = get_standard_puzzle_with_safe(source_pubkey, target_pubkey, source_claim_time, preimage_hash)

    # It's at this point that the target might disappear in an attempt to keep your coins locked up for a while
    # 3) Source claims their coins back
    pay_to_source_puzzle_hash = puzzle_for_pk(source_pubkey).get_tree_hash()
    create_coin_delegated_puzzle = Program.to(
        (1, [[ConditionOpcode.CREATE_COIN, pay_to_source_puzzle_hash, arbitrary_amount]])
    )
    cost, result = source_built_puzzle.run_with_cost(
        solution_for_hidden_puzzle(
            (source_pubkey + target_pubkey),
            generate_safe_puzzle(source_pubkey, target_pubkey, source_claim_time, preimage_hash),
            generate_safe_solution("", 0, create_coin_delegated_puzzle, Program.to(0)),
        )
    )
    expected_pay_to_source_result = Program.to(
        [
            [ConditionOpcode.ASSERT_HEIGHT_NOW_EXCEEDS, source_claim_time.to_bytes(4, "big")],
            [ConditionOpcode.AGG_SIG_ME, source_pubkey, create_coin_delegated_puzzle.get_tree_hash()],
            [ConditionOpcode.CREATE_COIN, pay_to_source_puzzle_hash, arbitrary_amount],
        ]
    )
    assert result == expected_pay_to_source_result


# This tests the scenario in which all coins are locked up properly,
# but either party needs to claim with a preimage because the other has disappeared.

# The main difference from the test above is that the swap completes properly
def test_claim_with_preimage():
    arbitrary_amount = 50
    key_store = KeyTool()

    # Illustration of how protocol works in ideal scenario
    # 1) "Target" sends pubkey to source
    target_pubkey = G1Element.from_bytes(public_key_for_index(0, key_store))

    # 2) "Source" builds standard atomic swap and publishes their spend
    source_pubkey = G1Element.from_bytes(public_key_for_index(1, key_store))
    preimage = "preimage"
    preimage_hash = std_hash(bytes(preimage, "utf-8"))
    # source_claim_time = 1000
    # source_built_puzzle = get_standard_puzzle_with_safe(source_pubkey,target_pubkey,source_claim_time,preimage_hash)

    # 3) Target verifies that a coin with the above info is on the blockchain and creates a mirror transaction
    target_claim_time = 500
    target_built_puzzle = get_standard_puzzle_with_safe(target_pubkey, source_pubkey, target_claim_time, preimage_hash)

    # 4) Source verifies that a coin with the above info is on the blockchain

    # It's at this point that the target may disappear, maybe innocently, or after receiving the source's honest payment
    # 5) Source claim's the target's coins with preimage
    pay_to_source_puzzle_hash = puzzle_for_pk(source_pubkey).get_tree_hash()
    create_coin_delegated_puzzle = Program.to(
        (1, [[ConditionOpcode.CREATE_COIN, pay_to_source_puzzle_hash, arbitrary_amount]])
    )
    cost, result = target_built_puzzle.run_with_cost(
        solution_for_hidden_puzzle(
            (source_pubkey + target_pubkey),
            generate_safe_puzzle(target_pubkey, source_pubkey, target_claim_time, preimage_hash),
            generate_safe_solution(preimage, 1, create_coin_delegated_puzzle, Program.to(0)),
        )
    )
    expected_pay_to_source_result = Program.to(
        [
            [ConditionOpcode.AGG_SIG_ME, source_pubkey, create_coin_delegated_puzzle.get_tree_hash()],
            [ConditionOpcode.CREATE_COIN, pay_to_source_puzzle_hash, arbitrary_amount],
        ]
    )

    assert result == expected_pay_to_source_result
