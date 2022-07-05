from chia.wallet.puzzles.load_clvm import load_clvm

P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer.clvm")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")
