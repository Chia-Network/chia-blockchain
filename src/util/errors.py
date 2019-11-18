class InvalidProtocolMessage(Exception):
    """Invalid protocol message function name"""


class InvalidHandshake(Exception):
    """Handshake message from peer is invalid"""


class InvalidAck(Exception):
    """Handshake message from peer is invalid"""


class IncompatibleProtocolVersion(Exception):
    """Protocol versions incompatible"""


class DuplicateConnection(Exception):
    """Already have connection with peer"""


class TooManyheadersRequested(Exception):
    """Requested too many header blocks"""


class TooManyBlocksRequested(Exception):
    """Requested too many blocks"""


class BlockNotInBlockchain(Exception):
    """Block not in blockchain"""


class NoProofsOfSpaceFound(Exception):
    """No proofs of space found for this challenge"""


class PeersDontHaveBlock(Exception):
    """None of our peers have the block we want"""


# Consensus errors
class InvalidWeight(Exception):
    """The weight of this block can not be validated"""


class InvalidUnfinishedBlock(Exception):
    """The unfinished block we received is invalid"""


class InvalidGenesisBlock(Exception):
    """Genesis block is not valid according to the consensus constants and rules"""
