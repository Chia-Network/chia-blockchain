from typing import Dict, Any

# Uncomment to generate new GENESIS_BLOCK
# from tests.block_tools import BlockTools

# bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 5,
    "DISCRIMINANT_SIZE_BITS": 16,
    "BLOCK_TIME_TARGET": 10,
    "DIFFICULTY_FACTOR": 3,
    "DIFFICULTY_WARP_FACTOR": 4,  # DELAY divides EPOCH in order to warp efficiently.
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
    "MIN_ITERS_STARTING": 50 * 2,
    "COINBASE_FREEZE_PERIOD": 0,
    "GENESIS_BLOCK": b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x15N3\xd3\xf9H\xc2K\x96\xfe\xf2f\xa2\xbf\x87\x0e\x0f,\xd0\xd4\x0f6s\xb1\".\\\xf5\x8a\xb4\x03\x84\x8e\xf9\xbb\xa1\xca\xdef3:\xe4?\x0c\xe5\xc6\x12\x80\x17\xd2\xcc\xd7\xb4m\x94\xb7V\x959\xed4\x89\x04b\x08\x07^\xca`\x8f#%\xe9\x9c\x9d\x86y\x10\x96W\x9d\xce\xc1\x15r\x97\x91U\n\x11<\xdf\xb2\xfc\xfb<\x13\x00\x00\x00\x98\xf4\x88\xcb\xb2MYo]\xaf \xd8a>\x06\xfe\xc8F\x8d\x15\x90\x15\xbb\x04\xd48\x10\xc6\xd8b\x82\x88\x7fx<\xe5\xe6\x8b\x8f\x84\xdd\x1cU\"\x83\xfb7\x9d`\xb0I\xb3\xbe;bvE\xc6\x92\xdd\xbe\x988\xe9y;\xc6.\xa1\xce\x94\xdc\xd8\xab\xaf\xba\x8f\xd8r\x8br\xc8\xa0\xac\xc0\xe9T\x87\x08\x08\x8b#-\xb6o\xf0\x1f\x0bzv\xb3\x81\x1a\xd4\xf7\x01\xdf\xc5A\x11\xe0\x0c\xc0\x87\xa6\xc2v\xbbR\xc4{\"\xa5\xe5\xe0bx7\xfa\n\xae\xea\xfe\x02\xac\xef\xec\xd1\xc2\xc55\x06{\xe1\x0c\xb2\x99q\xd7\xd8\xcb\x97\x86\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x17\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x04\x00(\x00\x17\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00^\x9f\xd4\xf8\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00}\xe7@\xfc\xa6\xaf\xc6\xec\xe8\xba\x19\xa3\x9b\x19vq\x91C\xa2\xe3\xde\x1f\xf1zB.\xf2\xc2\xc3,\x06\xa0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x00\x00\x00\x00\x00\x00\x08\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x8b)\xaa\x96x8\xd76J\xa6\x8b[\x98\t\xe0\\\xe3^7qD\x8c\xf5q\x08\xf2\xa2\xc9\xb03mv\x06\xf0[Y\xd3\xb2\x00\x00\xcdT/\x97BC\xb7\xdf\x85g\xcc\xe5\x15\xff\x1c\x05.6\xeen5+\x19;\xf4\xd9qS\xdfS\x18f\r|\xa7\xc1\xf9MW\xa1\xdb\xf9\x04\x9eL^\xf8\x84\n:\xbb\x8b\x8f\xd0':\xbfO\xd9Y\xb7\xfc\x15\xa9:\xd2\xd2.\xca\x13f\xa4e\x9a\x07\xc8\x0by+\x930\xa0\xd6\xe6\xbf\x16\xfbB\xc9\x85\xdd\x97J\x93m\x1e\x8c\xb9\x01%\x17\xc8\x17\xfe\xade\x02\x87\xd6\x1b\xdd\x9ch\x80;k\xf9\xc6A3\xdc\xab>e\xb5\xa5\x0c\xb9\x8b)\xaa\x96x8\xd76J\xa6\x8b[\x98\t\xe0\\\xe3^7qD\x8c\xf5q\x08\xf2\xa2\xc9\xb03mv\x00\x00\x01\xd1\xa9J \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00p\xc7\xd4\x8a3\x98\x00)\r0\xb7\x83!Z\xf9\x99\x95\xaeS\x1cI\xa9G\xa9\x85,\xb6z\xe7\x05\xcb\xaa\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00NS\xcb\x8a\xe7\x94i\x95r'\x1cWz6I\x19X\xfb\xa83hH*4\xe4\x15\x08\xbb\x05\tDpr\n\x88'gt\xbaX\xa3\xbc\xeah\xb9J\x8b9\x17\xbd\x08Yy\x15\x9b\x05\x14\rA\xb5n]?Q\xb7\x15:\x83\xdd\xd7\xa9\xc6tJ\xd9\xdf\x07\x081G \xcd:\x1d\x822\xb7\x11\xcfG\xc9U\xc3\xf7\x17\x8b\x00\x00",  # noqa: E501
}

# test_constants["GENESIS_BLOCK"] = bytes(
# bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
# )

# print(test_constants["GENESIS_BLOCK"])
