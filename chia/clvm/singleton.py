from chia.wallet.puzzles.load_clvm import load_clvm

P2_SINGLETON_MOD = load_clvm("p2_singleton.clsp", package_or_requirement="chia.wallet.puzzles")
SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer.clsp", package_or_requirement="chia.wallet.puzzles")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clsp", package_or_requirement="chia.wallet.puzzles")
