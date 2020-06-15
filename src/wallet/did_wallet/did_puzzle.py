from clvm_tools import binutils
from src.types.program import Program


def create_core():

    return " "


def create_innerpuz():

    return ""


def create_fullpuz(core, innerpuzhash):
    puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
    result = Program(binutils.assemble(puzstring))
    return result
