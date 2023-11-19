from __future__ import annotations

from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

P2_SINGLETON_MOD = load_clvm_maybe_recompile("p2_singleton.clsp")
SINGLETON_TOP_LAYER_MOD = load_clvm_maybe_recompile("singleton_top_layer.clsp")
SINGLETON_LAUNCHER = load_clvm_maybe_recompile("singleton_launcher.clsp")
