class InvalidHandshake(Exception):
    """Handshake message from peer is invalid"""
    pass


class IncompatibleProtocolVersion(Exception):
    """Protocol versions incompatible"""
    pass


class DuplicateConnection(Exception):
    """Already have connection with peer"""
    pass
