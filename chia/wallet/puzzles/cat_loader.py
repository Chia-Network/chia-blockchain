from chia.wallet.puzzles.load_clvm import load_clvm

CAT_MOD = load_clvm("cat_v2.clvm", package_or_requirement=__name__)
LOCK_INNER_PUZZLE = load_clvm("lock.inner.puzzle.clvm", package_or_requirement=__name__)

CAT_MOD_HASH = CAT_MOD.get_tree_hash()
