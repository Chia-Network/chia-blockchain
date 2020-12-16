from src.wallet.puzzles.load_clvm import load_clvm

GENERATOR_MOD = load_clvm("generator.clvm", package_or_requirement=__name__)
GENERATOR_FOR_SINGLE_COIN_MOD = load_clvm("generator_for_single_coin.clvm", package_or_requirement=__name__)
