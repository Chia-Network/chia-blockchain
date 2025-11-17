from chia.wallet.puzzles.load_clvm import load_clvm

SHATREE = load_clvm(
    "shatree_prog.clsp", package_or_requirement="chia._tests.generator.puzzles"
)

TEST_SUBSTR = load_clvm(
    "test_substr.clsp", package_or_requirement="chia._tests.generator.puzzles"
)

def test_whatever():
    breakpoint()