import pytest

from chia.wallet.chialisp import (
    apply,
    args,
    cons,
    eval,
    fail,
    first,
    is_zero,
    make_if,
    make_list,
    nth,
    quote,
    rest,
    sexp,
)


class TestChialisp:
    def test_sexp(self):
        assert sexp() == "()"
        assert sexp(1) == "(1)"
        assert sexp(1, 2) == "(1 2)"

    def test_cons(self):
        assert cons(1, 2) == "(c 1 2)"

    def test_first(self):
        assert first("(1)") == "(f (1))"

    def test_rest(self):
        assert rest("(1)") == "(r (1))"

    def test_nth(self):
        assert nth("val") == "val"
        assert nth("val", 0) == "(f val)"
        assert nth("val", 1) == "(f (r val))"
        assert nth("val", 2) == "(f (r (r val)))"
        assert nth("val", 2, 0) == "(f (f (r (r val))))"
        assert nth("val", 2, 1) == "(f (r (f (r (r val)))))"
        assert nth("val", 2, 2) == "(f (r (r (f (r (r val))))))"
        with pytest.raises(ValueError):
            nth("val", -1)

    def test_args(self):
        assert args() == "1"
        assert args(0) == "2"
        assert args(1) == "5"
        assert args(2) == "11"
        assert args(2, 0) == "22"
        assert args(2, 1) == "45"
        assert args(2, 2) == "91"
        with pytest.raises(ValueError):
            args(-1)

    def test_eval(self):
        assert eval("code") == "(a code 1)"
        assert eval("code", "env") == "(a code env)"

    def test_apply(self):
        assert apply("f", ()) == ("(f)")
        assert apply("f", ("1")) == ("(f 1)")
        assert apply("f", ("1", "2")) == ("(f 1 2)")

    def test_quote(self):
        assert quote(1) == "(q . 1)"

    def test_make_if(self):
        assert make_if("p", "t", "f") == "(a (i p (q . t) (q . f)) 1)"

    def test_make_list(self):
        # Note that nil is self-quoting now
        assert make_list() == "()"
        assert make_list(1) == "(c 1 ())"
        assert make_list(1, 2) == "(c 1 (c 2 ()))"

    def test_fail(self):
        assert fail("error") == "(x error)"

    def test_is_zero(self):
        assert is_zero("(q . 1)") == "(= (q . 1) (q . 0))"
