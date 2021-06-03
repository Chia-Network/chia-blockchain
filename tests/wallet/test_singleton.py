from clvm_tools import binutils

from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.condition_tools import parse_sexp_to_conditions
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clvm")
POOL_ESCAPING_MOD = load_clvm("pool_escaping_innerpuz.clvm")

LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()

LAUNCHER_ID = Program.to(b"launcher-id").get_tree_hash()
POOL_REWARD_PREFIX_MAINNET = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000000000")


def singleton_puzzle(launcher_id: Program, launcher_puzzle_hash: bytes32, inner_puzzle: Program) -> Program:
    return SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, launcher_puzzle_hash, inner_puzzle)


def p2_singleton_puzzle(launcher_id: Program, launcher_puzzle_hash: bytes32) -> Program:
    return P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, launcher_puzzle_hash)


def singleton_puzzle_hash(launcher_id: Program, launcher_puzzle_hash: bytes32, inner_puzzle: Program) -> bytes32:
    return singleton_puzzle(launcher_id, launcher_puzzle_hash, inner_puzzle).get_tree_hash()


def p2_singleton_puzzle_hash(launcher_id: Program, launcher_puzzle_hash: bytes32) -> bytes32:
    return p2_singleton_puzzle(launcher_id, launcher_puzzle_hash).get_tree_hash()


def test_only_odd_coins():
    did_core_hash = SINGLETON_MOD.get_tree_hash()
    # (MOD_HASH LAUNCHER_ID INNERPUZ parent_info my_amount inner_solution)
    solution = Program.to(
        [
            did_core_hash,
            LAUNCHER_ID,
            LAUNCHER_PUZZLE_HASH,
            Program.to(binutils.assemble("(q (51 0xcafef00d 200))")),
            [0xDEADBEEF, 0xCAFEF00D, 200],
            200,
            [],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception as e:
        assert e.args == ("clvm raise",)
    else:
        assert False

    solution = Program.to(
        [
            did_core_hash,
            LAUNCHER_ID,
            LAUNCHER_PUZZLE_HASH,
            1,
            [0xDEADBEEF, 0xCAFED00D, 210],
            205,
            [[51, 0xCAFEF00D, 205]],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception:
        assert False


def test_only_one_odd_coin_created():
    did_core_hash = SINGLETON_MOD.get_tree_hash()
    solution = Program.to(
        [
            did_core_hash,
            LAUNCHER_ID,
            LAUNCHER_PUZZLE_HASH,
            1,
            [0xDEADBEEF, 0xCAFEF00D, 411],
            411,
            [[51, 0xCAFEF00D, 203], [51, 0xFADEDDAB, 203]],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception as e:
        assert e.args == ("clvm raise",)
    else:
        assert False
    solution = Program.to(
        [
            did_core_hash,
            LAUNCHER_ID,
            LAUNCHER_PUZZLE_HASH,
            1,
            [0xDEADBEEF, 0xCAFEF00D, 411],
            411,
            [[51, 0xCAFEF00D, 203], [51, 0xFADEDDAB, 202], [51, 0xFADEDDAB, 4]],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception:
        assert False


def test_p2_singleton():
    # create a singleton. This should call driver code.
    launcher_id = LAUNCHER_ID
    innerpuz = Program.to(1)
    singleton_full_puzzle = singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH, innerpuz)

    # create a fake coin id for the `p2_singleton`
    p2_singleton_coin_id = Program.to(["test_hash"]).get_tree_hash()
    expected_announcement = Announcement(singleton_full_puzzle.get_tree_hash(), p2_singleton_coin_id).name()

    # create a `p2_singleton` puzzle. This should call driver code.
    p2_singleton_full = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution = Program.to([innerpuz.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    err, conditions = parse_sexp_to_conditions(result)
    assert err is None

    p2_singleton_full = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution = Program.to([innerpuz.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    assert result.first().rest().first().as_atom() == expected_announcement
    assert conditions[0].vars[0] == expected_announcement


def test_pool_puzzles():
    # See also tests/pools/test_pool_puzzles.py
    # create a singleton with id `launcher_id`
    launcher_parent_id = Program.to(b"launcher-parent").get_tree_hash()
    launcher_coin = Coin(launcher_parent_id, LAUNCHER_PUZZLE.get_tree_hash(), 200)
    launcher_id = launcher_coin.name()

    # create a `p2_singleton` that's provably a block reward
    genesis_challenge = bytes.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")
    block_height = 101  # 0x65
    pool_reward_parent_id = bytes32(genesis_challenge[:16] + block_height.to_bytes(16, "big"))

    p2_singleton_full_puzhash = p2_singleton_puzzle_hash(launcher_id, LAUNCHER_PUZZLE_HASH)
    p2_singleton_coin_amount = 2000000000
    p2_singleton_coin_id = Coin(pool_reward_parent_id, p2_singleton_full_puzhash, p2_singleton_coin_amount).name()

    # here are some pool parameters
    pool_puzzle_hash = 0xD34DB33F
    relative_lock_height = 600
    owner_pubkey = 0xFADEDDAB

    # Only the escape puzzle has RELATIVE_LOCK_HEIGHT
    # Curry params are POOL_PUZHASH, RELATIVE_LOCK_HEIGHT, OWNER_PUBKEY, P2_SINGLETON_PUZHASH
    escape_innerpuz = POOL_ESCAPING_MOD.curry(
        pool_puzzle_hash,
        p2_singleton_full_puzhash,
        owner_pubkey,
        genesis_challenge[:16] + bytes([0] * 16),
        relative_lock_height,
    )
    # Curry params are POOL_PUZHASH, RELATIVE_LOCK_HEIGHT, ESCAPE_MODE_PUZHASH, P2_SINGLETON_PUZHASH, PUBKEY
    escape_innerpuz_hash = escape_innerpuz.get_tree_hash()
    committed_innerpuz = POOL_MEMBER_MOD.curry(
        pool_puzzle_hash,
        p2_singleton_full_puzhash,
        owner_pubkey,
        genesis_challenge[:16] + bytes([0] * 16),
        escape_innerpuz_hash,
    )

    # the singleton is committed to the pool
    singleton_full = singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH, committed_innerpuz)
    singleton_amount = 3
    singleton_coin = Coin(launcher_id, singleton_full.get_tree_hash(), singleton_amount)

    # innersol = spend_type pool_reward_amount pool_reward_height extra_data
    inner_sol = Program.to([0, p2_singleton_coin_amount, block_height, "bonus data"])
    # full_sol = parent_info, my_amount, inner_solution
    full_sol = Program.to([[launcher_coin.parent_coin_info, launcher_coin.amount], singleton_amount, inner_sol])
    cost, result = singleton_full.run_with_cost(INFINITE_COST, full_sol)
    """
    Retrieves all entries for a wallet ID from the cache, works even if commit is not called yet."""

    conditions = result.as_python()
    assert bytes32(result.first().rest().first().as_atom()) == singleton_coin.name()
    assert (
        bytes32(result.rest().rest().rest().rest().first().rest().first().as_atom())
        == Announcement(p2_singleton_coin_id, bytes.fromhex("80")).name()
    )
    assert conditions[-1][1] == Announcement(p2_singleton_coin_id, bytes.fromhex("80")).name()
    assert bytes32(conditions[1][1]) == singleton_full.get_tree_hash()

    # new_result = '((70 0xe5a82aba773956ba319c74bae988ef5690d23d515d305640e963274e35ed6d44) (51 0x22e106ec75eaa42c63fa92fd36f68be0617d1200474df06cf88cb83d31b42938 3) (51 0x00d34db33f 0x77359400) (62 0xe6953e9190bdc44f47e95fbcbd56c3e444960097b9764e2b396141dff194e77c) (61 0x548607847d230749d38064b7ff43d390cafea3c51ac4cf15d86114dcd957c264))'  # noqa
    # result = '((70 0x90b2708399fadb0f35aaf0d7a0973045214180ce45d6968a5cdaba749dbf0ca6) (61 0x93e1b4675d94b6edf31bcfdca9bb2ce3c3da28715fe628b577c48a787dc3e440) (62 0x881b7255ced9576bd8782b6efec2ec9ce46b8b08500125092a69645c754d09cb) (51 0x00d34db33f 0x77359400) (51 0xa4878510fee591565037bf60c38e58445d1d451a7374d8d7f44db2c8a3107806 3))'  # noqa
