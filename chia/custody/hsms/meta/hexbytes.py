class hexbytes(bytes):
    """
    This is a subclass of bytes that prints itself out as hex,
    which is much easier on the eyes for binary data that is very non-ascii .
    """

    def __str__(self):
        return self.hex()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, str(self))
