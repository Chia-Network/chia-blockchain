#!/usr/bin/env python

import argparse
import os.path

from hsms.process.sign import generate_synthetic_offset_signatures
from hsms.streamables import SpendBundle
from hsms.util.qrint_encoding import a2b_qrint, b2a_qrint


def create_spend_bundle(unsigned_spend, signatures):

    extra_signatures = generate_synthetic_offset_signatures(unsigned_spend)

    # now let's try adding them all together and creating a `SpendBundle`

    all_signatures = signatures + [sig_info.signature for sig_info in extra_signatures]
    total_signature = sum(all_signatures, start=all_signatures[0].zero())

    return SpendBundle(unsigned_spend.coin_spends, total_signature)


def file_or_string(p) -> str:
    try:
        with open(p) as f:
            text = f.read().strip()
    except Exception:
        text = p
    return text


def decode(path):
    if path.endswith(".qri") and len(path) > 4:
        new_path = path[:-4]
    else:
        new_path = path + ".bin"
    if os.path.exists(new_path):
        raise ValueError(f"{new_path} already exists")

    blob = open(path).read().strip()
    decoded = a2b_qrint(blob)
    with open(new_path, "wb") as f:
        f.write(decoded)


def encode(path):
    new_path = path + ".qri"
    if os.path.exists(new_path):
        raise ValueError(f"{new_path} already exists")

    blob = open(path, "rb").read()
    encoded = b2a_qrint(blob)
    with open(new_path, "w") as f:
        f.write(encoded)


def qrint(args, parser):
    with open(args.path, "rb") as f:
        blob = f.read()

    is_qrint = (
        all(c in b"0123456789" for c in blob.strip()) and not args.encode_to_qrint
    )

    if is_qrint:
        return decode(args.path)
    else:
        return encode(args.path)


def create_parser():
    parser = argparse.ArgumentParser(description="Convert binary to/from qrint format.")
    parser.add_argument(
        "-e",
        "--encode-to-qrint",
        action="store_true",
        help="force conversion from binary to qrint",
    )
    parser.add_argument(
        "path",
        metavar="path-to-binary-or-qrint-file",
        help="file containing qrint or binary (context-sensitive)",
    )
    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    return qrint(args, parser)


if __name__ == "__main__":
    main()
