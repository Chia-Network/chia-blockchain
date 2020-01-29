def address_for_puzzle_hash(puzzle_hash):
    """
    Turn the puzzle hash into a human-readable address.
    Eventually this will use BECH32.
    """
    return puzzle_hash.hex()


def puzzle_hash_for_address(address):
    """
    Turn a human-readable address into a binary puzzle hash
    Eventually this will use BECH32.
    """
    return bytes.fromhex(address)
