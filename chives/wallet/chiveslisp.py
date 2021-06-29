def sexp(*argv):
    return f'({f" ".join([str(arg) for arg in argv])})'


def cons(a, b):
    return sexp("c", a, b)


def first(obj):
    return sexp("f", obj)


def rest(obj):
    return sexp("r", obj)


def nth(obj, *path):
    if not path:
        return obj
    if path[0] < 0:
        raise ValueError
    if path[0] == 0:
        return nth(first(obj), *path[1:])
    else:
        return nth(rest(obj), *(path[0] - 1,) + path[1:])


def args(*path, p=1):
    if len(path) == 0:
        return str(p)
    if path[0] < 0:
        raise ValueError
    return args(*path[1:], p=(2 * p << path[0]) | (2 ** path[0] - 1))


def eval(code, env=args()):
    return sexp("a", code, env)


def apply(name, argv):
    return sexp(*[name] + list(argv))


def quote(obj):
    return sexp("q .", obj)


nil = sexp()


def make_if(predicate, true_expression, false_expression):
    return eval(apply("i", [predicate, quote(true_expression), quote(false_expression)]))


def make_list(*argv, terminator=nil):
    if len(argv) == 0:
        return terminator
    else:
        return cons(argv[0], make_list(*argv[1:], terminator=terminator))


def fail(*argv):
    return apply("x", argv)


def sha256(*argv):
    return apply("sha256", argv)


SHA256TREE_PROG = """
(a (q . (a 2 (c 2 (c 3 0))))
    (c (q . (a (i (l 5)
                 (q . (sha256 (q . 2)
                            (a 2 (c 2 (c 9 0)))
                            (a 2 (c 2 (c 13 0)))))
                 (q . (sha256 (q . 1) 5))) 1)) %s))
"""


def sha256tree(*argv):
    return SHA256TREE_PROG % argv[0]


def equal(*argv):
    return apply("=", argv)


def multiply(*argv):
    return apply("*", argv)


def add(*argv):
    return apply("+", argv)


def subtract(*argv):
    return apply("-", argv)


def is_zero(obj):
    return equal(obj, quote("0"))


def iff(*argv):
    return apply("i", argv)


def hexstr(str):
    return quote(f"0x{str}")


def greater(*argv):
    return apply(">", argv)


def string(str):
    return f'"{str}"'
