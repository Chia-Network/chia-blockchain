import cbor

from chiasim.atoms import hexbytes
from chiasim.hashable import BLSSignature, CoinSolution, Program


def remap(s, f):
    """
    Iterate through a json-like structure, applying remap(_, f) recursively
    to all items in collectives and f(_) to all non-collectives
    within the structure.
    """
    if isinstance(s, list):
        return [remap(_, f) for _ in s]
    if isinstance(s, tuple):
        return tuple([remap(_, f) for _ in s])
    if isinstance(s, dict):
        return {remap(k, f): remap(v, f) for k, v in s.items()}
    return f(s)


def use_hexbytes(s):
    """
    Dig through json-like structure s and replace all instances of bytes
    with hexbytes so the repr isn't as ugly.
    """

    def to_hexbytes(s):
        if isinstance(s, bytes):
            return hexbytes(s)
        return s

    return remap(s, to_hexbytes)


def cbor_struct_to_bytes(s):
    """
    Dig through json-like structure s and replace t with bytes(t) for
    every substructure t that supports it. This prepares a structure to
    be serialized with cbor.
    """

    def to_bytes(k):
        if hasattr(k, "__bytes__"):
            return bytes(k)
        return k

    return remap(s, to_bytes)


class PartiallySignedTransaction(dict):
    @classmethod
    def from_bytes(cls, blob):
        pst = use_hexbytes(cbor.loads(blob))
        return cls(transform_pst(pst))

    def __bytes__(self):
        cbor_obj = cbor_struct_to_bytes(self)
        return cbor.dumps(cbor_obj)


def xform_aggsig_sig_pair(pair):
    """
    Transform a pair (aggsig_pair_bytes, sig_bytes)
    to (aggsig_pair, BLSSignature).
    """
    aggsig = BLSSignature.aggsig_pair.from_bytes(pair[0])
    sig = BLSSignature.from_bytes(pair[1])
    return (aggsig, sig)


def xform_list(item_xform):
    """
    Return a function that transforms a list of items by calling
    item_xform(_) on each element _ in the list.
    """

    def xform(item_list):
        return [item_xform(_) for _ in item_list]

    return xform


def transform_dict(d, xformer):
    """
    Transform elements of the dict d using the xformer (also a dict,
    where the keys match the keys in d and the values of d are transformed
    by invoking the correspding values in xformer.
    """
    for k, v in xformer.items():
        if k in d:
            d[k] = v(d[k])
    return d


PST_TRANSFORMS = dict(
    coin_solutions=xform_list(CoinSolution.from_bytes),
    sigs=xform_list(xform_aggsig_sig_pair),
    delegated_solution=Program.from_bytes,
)


def transform_pst(pst):
    """
    Turn a pst dict with everything streamed into bytes into its
    corresponding constituent parts.
    """
    return transform_dict(pst, PST_TRANSFORMS)
