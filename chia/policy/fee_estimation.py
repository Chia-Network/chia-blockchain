class FeeMempoolInfo:
    """
    Information from Mempool and MempoolItems needed to estimate fees.

    Attributes:
        current_cost (int):This is the current capacity of the mempool, measured in XCH per CLVM Cost
        max_cost (int): This is the maximum capacity of the mempool, measured in XCH per CLVM Cost

    """


class FeeBlockInfo:
    """
    Information from Blockchain needed to estimate fees.
    """

    pass


class FeeRate:
    """
    Represents Fee in XCH per CLVM Cost. Performs XCH/mojo conversion
    """

    pass
