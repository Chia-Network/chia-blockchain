from ...atoms import hash_pointer
from ..hashable import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint64
from .Body import Body
from .Hash import std_hash
from .ProofOfSpace import ProofOfSpace
from .Signature import Signature


@streamable
class Header(Streamable):
    """
    A header is the main linked structure of the blockchain. It
    includes a link to previous header (with the first header containing
    a link to a magic terminal "genesis header"), a link to the
    proof of space, a link to the body (which includes all this block's
    transactions), and a link to an extension block, whose purpose is
    not defined at launch, but might vary in future soft forks.
    """
    previous_hash: "HeaderHash"
    previous_signature: Signature
    timestamp: uint64
    proof_of_space_hash: hash_pointer(ProofOfSpace, std_hash)
    body_hash: hash_pointer(Body, std_hash)
    extension_data_hash: bytes32


HeaderHash = hash_pointer(Header, std_hash)
Header.__annotations__["previous_hash"] = HeaderHash
