#!/usr/bin/env python3

# A simple/silly tool for generating a mnemonic with known words. Possibly useful for testing.
# Usage:
#  $ python tools/mnemonic_generator.py exotic toilet dance
#  exotic toilet dance <rest of mnemonic>

import argparse
import sys

from bitstring import BitArray
from chia.util.keychain import bip39_word_list, bytes_to_mnemonic
from secrets import token_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--list", action="store_true")
    parser.add_argument("words", type=str, nargs="*", help="words to use in mnemonic (may specify up to 23)")

    list = None
    words = None

    for key, value in vars(parser.parse_args()).items():
        if key == "list":
            list = value
        elif key == "words":
            words = value
        else:
            print(f"Invalid argument {key}")

    if not list and len(words) == 0:
        print("Example usage:")
        print("python mnemonic_generator.py exotic toilet dance")
        sys.exit(1)

    word_list = bip39_word_list().splitlines()

    if list:
        for word in word_list:
            print(word)
        sys.exit(0)

    bitarray = BitArray(token_bytes(32))

    for i, word in enumerate(words):
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


if __name__ == "__main__":
    main()
