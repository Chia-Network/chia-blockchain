from chia.types.blockchain_format.program import Program, SerializedProgram, INFINITE_COST
from chia.wallet.puzzles.load_clvm import load_clvm
from clvm_tools.binutils import assemble

SHA256TREE_MOD = load_clvm("sha256tree_module.clvm")


# TODO: test multiple args
def test_tree_hash():
    p = SHA256TREE_MOD
    s = SerializedProgram.from_bytes(bytes(SHA256TREE_MOD))
    assert s.get_tree_hash() == p.get_tree_hash()


def test_program_execution():
    p_result = SHA256TREE_MOD.run(SHA256TREE_MOD)
    sp = SerializedProgram.from_bytes(bytes(SHA256TREE_MOD))
    cost, sp_result = sp.run_with_cost(INFINITE_COST, sp)
    assert p_result == sp_result


def test_serialization():
    s0 = SerializedProgram.from_bytes(b"\x00")
    p0 = Program.from_bytes(b"\x00")
    print(s0, p0)
    assert bytes(p0) == bytes(s0)


def check_idempotency(f, *args):
    prg = Program.to(f)
    curried = prg.curry(*args)

    sprg = SerializedProgram.from_bytes(bytes(prg))
    scurried = sprg.curry(*args)

    assert bytes(scurried) == bytes(curried)


def test_curry():

    f = assemble("(+ 2 5)")
    check_idempotency(f, 200, 30)

    f = assemble("(+ 2 5)")
    args = assemble("(+ (q . 50) (q . 60))")
    # passing "args" here wraps the arguments in a list
    check_idempotency(f, args)
