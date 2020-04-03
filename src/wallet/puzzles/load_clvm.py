import pkg_resources

from src.types.program import Program


def load_clvm(filename):
    clvm_hex = pkg_resources.resource_string(__name__, "%s.hex" % filename).decode(
        "utf8"
    )
    clvm_blob = bytes.fromhex(clvm_hex)
    return Program.from_bytes(clvm_blob)
