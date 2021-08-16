from chia.wallet.puzzles.load_clvm import load_clvm

CC_MOD = load_clvm("cc.clsp", package_or_requirement=__name__)
LOCK_INNER_PUZZLE = load_clvm("lock.inner.puzzle.clsp", package_or_requirement=__name__)
