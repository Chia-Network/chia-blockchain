class InvalidHandshake(Exception):
    """Handshake message from peer is invalid"""
    pass


class IncompatibleProtocolVersion(Exception):
    """Protocol versions incompatible"""
    pass


class DuplicateConnection(Exception):
    """Already have connection with peer"""
    pass


class TooManyTrunksRequested(Exception):
    """Requested too many trunk blocks"""
    pass


class TooManyBlocksRequested(Exception):
    """Requested too many blocks"""
    pass


class BlockNotInBlockchain(Exception):
    """Block not in blockchain"""
    pass

# Consensus errors

class InvalidWeight(Exception):
    """The weight of this block can not be validated"""
    pass