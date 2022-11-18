from typing import Iterator, List, Tuple, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.coin_spend import CoinSpend
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.lineage_proof import LineageProof
from chia.util.ints import uint64
from chia.util.hash import std_hash

SINGLETON_MOD = load_clvm_maybe_recompile("singleton_top_layer.clvm")
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()
P2_SINGLETON_MOD = load_clvm_maybe_recompile("p2_singleton.clvm")
P2_SINGLETON_OR_DELAYED_MOD = load_clvm_maybe_recompile("p2_singleton_or_delayed_puzhash.clvm")
SINGLETON_LAUNCHER = load_clvm_maybe_recompile("singleton_launcher.clvm")
SINGLETON_LAUNCHER_HASH = SINGLETON_LAUNCHER.get_tree_hash()
ESCAPE_VALUE = -113
MELT_CONDITION = [ConditionOpcode.CREATE_COIN, 0, ESCAPE_VALUE]


#
# An explanation of how this functions from a user's perspective
#
# Consider that you have some coin A that you want to create a singleton
# containing some inner puzzle I from with amount T.  We'll call the Launcher
# coin, which is created from A "Launcher" and the first iteration of the
# singleton, called the "Eve" spend, Eve.  When spent, I yields a coin
# running I' and so on in a singleton specific way described below.
#
# The structure of this on the blockchain when done looks like this
#
#   ,------------.
#   | Coin A     |
#   `------------'
#         |
#  ------------------ Atomic Transaction 1 -----------------
#         v
#   .------------.       .-------------------------------.
#   | Launcher   |------>| Eve Coin Containing Program I |
#   `------------'       `-------------------------------'
#                                        |
#  -------------------- End Transaction 1 ------------------\
#                                        |                   > The Eve coin
#  --------------- (2) Transaction With I ------------------/  may also be
#                                        |                     spent
#                                        v                     simultaneously
#                 .-----------------------------------.
#                 | Running Singleton With Program I' |
#                 `-----------------------------------'
#                                        |
# --------------------- End Transaction 2 ------------------
#                                        |
# --------------- (3) Transaction With I' ------------------
# ...
#
#
# == Practical use of singleton_top_layer.py ==
#
# 1) Designate some coin as coin A
#
# 2) call puzzle_for_singleton with that coin's name (it is the Parent of the
#    Launch coin), and the initial inner puzzle I, curried as appropriate for
#    its own purpose. Adaptations of the program I and its descendants are
#    required as below.
#
# 3) call launch_conditions_and_coinsol to get a set of "launch_conditions",
#    which will be used to spend standard coin A, and a "spend", which spends
#    the Launcher created by the application of "launch_conditions" to A in a
#    spend. These actions must be done in the same spend bundle.
#
#    One can create a SpendBundle containing the spend of A giving it the
#    argument list (() (q . launch_conditions) ()) and then append "spend" onto
#    its .coin_spends to create a combined spend bundle.
#
# 4) submit the combine spend bundle.
#
# 5) Remember the identity of the Launcher coin:
#
#      Coin(A.name(), SINGLETON_LAUNCHER_HASH, amount)
#
# A singleton has been created like this:
#
#      Coin(Launcher.name(), puzzle_for_singleton(Launcher.name(), I), amount)
#
#
# == To spend the singleton requires some host side setup ==
#
# The singleton adds an ASSERT_MY_COIN_ID to constrain it to the coin that
# matches its own conception of itself.  It consumes a "LineageProof" object
# when spent that must be constructed so.  We'll call the singleton we intend
# to spend "S".
#
# Specifically, the required puzzle is the Inner puzzle I for the parent of S
# unless S is the Eve coin, in which case it is None.
# So to spend S', the second singleton, I is used, and to spend S'', I' is used.
# We'll call this puzzle hash (or None) PH.
#
#      If this is the Eve singleton:
#
#          PH = None
#          L = LineageProof(Launcher, PH, amount)
#
#       - Note: the Eve singleton's .parent_coin_info should match Launcher here.
#
#      Otherwise
#
#          PH = ParentOf(S).inner_puzzle_hash
#          L = LineageProof(ParentOf(S).name(), PH, amount)
#
#       - Note: ParentOf(S).name is the .parent_coin_info member of the
#         coin record for S.
#
# Now the coin S can be spent.
# The puzzle to use in the spend is given by
#
#      puzzle_for_singleton(S.name(), I'.puzzle_hash())
#
# and the arguments are given by (with the argument list to I designated AI)
#
#      solution_for_singleton(L, amount, AI)
#
# Note that AI contains dynamic arguments to puzzle I _after_ the singleton
# truths.
#
#
# Adapting puzzles to the singleton
#
# 1) For the puzzle to create a coin from inside the singleton it will need the
#    following values to be added to its curried in arguments:
#
#     - A way to compute its own puzzle has for each of I' and so on. This can
#       be accomplished by giving it its uncurried puzzle hash and using
#       puzzle-hash-of-curried-function to compute it.  Although full_puzzle_hash
#       is used for some arguments, the inputs to all singleton_top_layer
#       functions is the inner puzzle.
#
#     - the name() of the Launcher coin (which you can compute from a Coin
#       object) if you're not already using it in I puzzle for some other
#       reason.
#
# 2) A non-curried argument called "singleton_truths" will be passed to your
#    program.  It is not required to use anything inside.
#
#    There is little value in not receiving this argument via the adaptations
#    below as a standard puzzle can't be used anyway. To work the result must
#    be itself a singleton, and the singleton does not change the puzzle hash
#    in an outgoing CREATE_COIN to cause it to be one.
#
#    With this modification of the program I done, I and descendants will
#    continue to produce I', I'' etc.
#
#    The actual CREATE_COIN puzzle hash will be the result of
#    this.  The Launcher ID referred to here is the name() of
#    the Launcher coin as above.
#


def match_singleton_puzzle(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
    mod, curried_args = puzzle.uncurry()
    if mod == SINGLETON_MOD:
        return True, curried_args.as_iter()
    else:
        return False, iter(())


# Given the parent and amount of the launcher coin, return the launcher coin
def generate_launcher_coin(coin: Coin, amount: uint64) -> Coin:
    return Coin(coin.name(), SINGLETON_LAUNCHER_HASH, amount)


# Wrap inner puzzles that are not singleton specific to strip away "truths"
def adapt_inner_to_singleton(inner_puzzle: Program) -> Program:
    # (a (q . inner_puzzle) (r 1))
    return Program.to([2, (1, inner_puzzle), [6, 1]])


def adapt_inner_puzzle_hash_to_singleton(inner_puzzle_hash: bytes32) -> bytes32:
    puzzle = adapt_inner_to_singleton(Program.to(inner_puzzle_hash))
    return puzzle.get_tree_hash_precalc(inner_puzzle_hash)


def remove_singleton_truth_wrapper(puzzle: Program) -> Program:
    inner_puzzle = puzzle.rest().first().rest()
    return inner_puzzle


# Take standard coin and amount -> launch conditions & launcher coin solution
def launch_conditions_and_coinsol(
    coin: Coin,
    inner_puzzle: Program,
    comment: List[Tuple[str, str]],
    amount: uint64,
) -> Tuple[List[Program], CoinSpend]:
    if (amount % 2) == 0:
        raise ValueError("Coin amount cannot be even. Subtract one mojo.")

    launcher_coin: Coin = generate_launcher_coin(coin, amount)
    curried_singleton: Program = SINGLETON_MOD.curry(
        (SINGLETON_MOD_HASH, (launcher_coin.name(), SINGLETON_LAUNCHER_HASH)),
        inner_puzzle,
    )

    launcher_solution = Program.to(
        [
            curried_singleton.get_tree_hash(),
            amount,
            comment,
        ]
    )
    create_launcher = Program.to(
        [
            ConditionOpcode.CREATE_COIN,
            SINGLETON_LAUNCHER_HASH,
            amount,
        ],
    )
    assert_launcher_announcement = Program.to(
        [
            ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
            std_hash(launcher_coin.name() + launcher_solution.get_tree_hash()),
        ],
    )

    conditions = [create_launcher, assert_launcher_announcement]

    launcher_coin_spend = CoinSpend(
        launcher_coin,
        SINGLETON_LAUNCHER,
        launcher_solution,
    )

    return conditions, launcher_coin_spend


# Take a coin solution, return a lineage proof for their child to use in spends
def lineage_proof_for_coinsol(coin_spend: CoinSpend) -> LineageProof:
    parent_name: bytes32 = coin_spend.coin.parent_coin_info

    inner_puzzle_hash: Optional[bytes32] = None
    if coin_spend.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
        full_puzzle = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        r = full_puzzle.uncurry()
        if r is not None:
            _, args = r
            _, inner_puzzle = list(args.as_iter())
            inner_puzzle_hash = inner_puzzle.get_tree_hash()

    amount: uint64 = uint64(coin_spend.coin.amount)

    return LineageProof(
        parent_name,
        inner_puzzle_hash,
        amount,
    )


# Return the puzzle reveal of a singleton with specific ID and innerpuz
def puzzle_for_singleton(
    launcher_id: bytes32, inner_puz: Program, launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH
) -> Program:
    return SINGLETON_MOD.curry(
        (SINGLETON_MOD_HASH, (launcher_id, launcher_hash)),
        inner_puz,
    )


# Return a solution to spend a singleton
def solution_for_singleton(
    lineage_proof: LineageProof,
    amount: uint64,
    inner_solution: Program,
) -> Program:
    if lineage_proof.inner_puzzle_hash is None:
        parent_info = [
            lineage_proof.parent_name,
            lineage_proof.amount,
        ]
    else:
        parent_info = [
            lineage_proof.parent_name,
            lineage_proof.inner_puzzle_hash,
            lineage_proof.amount,
        ]

    return Program.to([parent_info, amount, inner_solution])


# Create a coin that a singleton can claim
def pay_to_singleton_puzzle(launcher_id: bytes32) -> Program:
    return P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, SINGLETON_LAUNCHER_HASH)


# Create a coin that a singleton can claim or that can be sent to another puzzle after a specified time
def pay_to_singleton_or_delay_puzzle(launcher_id: bytes32, delay_time: uint64, delay_ph: bytes32) -> Program:
    return P2_SINGLETON_OR_DELAYED_MOD.curry(
        SINGLETON_MOD_HASH,
        launcher_id,
        SINGLETON_LAUNCHER_HASH,
        delay_time,
        delay_ph,
    )


# Solution for EITHER p2_singleton or the claiming spend case for p2_singleton_or_delayed_puzhash
def solution_for_p2_singleton(p2_singleton_coin: Coin, singleton_inner_puzhash: bytes32) -> Program:
    return Program.to([singleton_inner_puzhash, p2_singleton_coin.name()])


# Solution for the delayed spend case for p2_singleton_or_delayed_puzhash
def solution_for_p2_delayed_puzzle(output_amount: uint64) -> Program:
    return Program.to([output_amount, []])


# Get announcement conditions for singleton solution and full CoinSpend for the claimed coin
def claim_p2_singleton(
    p2_singleton_coin: Coin,
    singleton_inner_puzhash: bytes32,
    launcher_id: bytes32,
    delay_time: Optional[uint64] = None,
    delay_ph: Optional[bytes32] = None,
) -> Tuple[Program, Program, CoinSpend]:
    assertion = Program.to([ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(p2_singleton_coin.name() + b"$")])
    announcement = Program.to([ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, p2_singleton_coin.name()])
    if delay_time is None or delay_ph is None:
        puzzle: Program = pay_to_singleton_puzzle(launcher_id)
    else:
        puzzle = pay_to_singleton_or_delay_puzzle(
            launcher_id,
            delay_time,
            delay_ph,
        )
    claim_coinsol = CoinSpend(
        p2_singleton_coin,
        puzzle,
        solution_for_p2_singleton(p2_singleton_coin, singleton_inner_puzhash),
    )
    return assertion, announcement, claim_coinsol


# Get the CoinSpend for spending to a delayed puzzle
def spend_to_delayed_puzzle(
    p2_singleton_coin: Coin,
    output_amount: uint64,
    launcher_id: bytes32,
    delay_time: uint64,
    delay_ph: bytes32,
) -> CoinSpend:
    claim_coinsol = CoinSpend(
        p2_singleton_coin,
        pay_to_singleton_or_delay_puzzle(launcher_id, delay_time, delay_ph),
        solution_for_p2_delayed_puzzle(output_amount),
    )
    return claim_coinsol
