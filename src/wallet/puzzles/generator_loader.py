from src.wallet.puzzles.load_clvm import load_clvm

GENERATOR_MOD = load_clvm("generator.clvm", package_or_requirement=__name__)
