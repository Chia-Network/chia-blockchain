from __future__ import annotations

from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

CAT_MOD = load_clvm_maybe_recompile("cat_v2.clvm", package_or_requirement=__name__)
LOCK_INNER_PUZZLE = load_clvm_maybe_recompile("lock.inner.puzzle.clvm", package_or_requirement=__name__)

CAT_MOD_HASH = CAT_MOD.get_tree_hash()
