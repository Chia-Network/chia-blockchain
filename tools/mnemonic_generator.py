#!/usr/bin/env python3

# A simple/silly tool for generating a mnemonic with known words. Possibly useful for testing.
# Usage:
#  $ python tools/mnemonic_generator.py exotic toilet dance
#  exotic toilet dance <rest of mnemonic>

import sys

from bitstring import BitArray
from chia.util.keychain import bip39_word_list, bytes_to_mnemonic
from secrets import token_bytes

if len(sys.argv) < 2:
    print("Usage: mnemonic_generator.py <word1> <word2> ... <word23>")
    sys.exit(1)

word_list = bip39_word_list().splitlines()
bitarray = BitArray(token_bytes(32))

for i, word in enumerate(sys.argv[1:]):
    try:
        word_index = word_list.index(word)
    except ValueError:
        print(f"Word not found in BIP39 word list: {word}")
        sys.exit(1)
    start = i * 11
    end = start + 11
    bitarray[start:end] = word_index

mnemonic_bytes = bitarray.bytes
mnemonic = bytes_to_mnemonic(mnemonic_bytes)

print(mnemonic)
