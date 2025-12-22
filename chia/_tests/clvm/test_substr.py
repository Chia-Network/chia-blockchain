from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.blockchain_format.program import Program

SHATREE: Program = load_clvm(
    "shatree_prog.clsp", package_or_requirement="chia._tests.generator.puzzles"
)

TEST_SUBSTR: Program = load_clvm(
    "test_substr.clsp", package_or_requirement="chia._tests.generator.puzzles"
)

def test_whatever():
    breakpoint()