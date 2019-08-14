from __future__ import print_function
import argparse
import sys
import time

from lib.chiavdf.inkfish.proof_of_time import create_proof_of_time_nwesolowski

from lib.chiavdf.inkfish.classgroup import ClassGroup
from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from src.types.classgroup import ClassgroupElement


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def create_pot_parser():
    parser = argparse.ArgumentParser(
        description='Generate or verify a proof of time using the Chia ' +
                    'Verfiable Delay Function (VDF)',
    )
    parser.add_argument("-t", "--type", default="wesolowski",
                        choices=["wesolowski", "n-wesolowski", "pietrzak"],
                        help="the type of proof, wesolowski, n-wesolowski, or pietrzak")
    parser.add_argument("-l", "--length", type=int, default=2048,
                        help="the number of bits of the discriminant")
    parser.add_argument("-d", "--depth", type=int, default=2,
                        help="depth of n-wesolowski (n) default is 2")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print a bunch of extra stuff about the proof")
    parser.add_argument("discriminant_challenge", type=bytes.fromhex,
                        help="a hex-encoded challenge used to derive the discriminant")
    parser.add_argument("iterations", type=int,
                        help="number of iterations")
    parser.add_argument("proof", type=bytes.fromhex,
                        help="the hex-encoded proof", nargs="?")
    return parser


def main():
    args = sys.argv
    parser = create_pot_parser()
    args = parser.parse_args(args=args[1:])
    discriminant = create_discriminant(args.discriminant_challenge, args.length)

    if args.verbose:
        print("proof type: %s" % args.type)
        print("discriminant: %s" % discriminant)
        print("discriminant size: %s" % args.length)

    # Generator element is created as a=2, b=1.
    x = ClassGroup.from_ab_discriminant(2, 1, discriminant)
    if args.verbose:
        print("x: %s" % str(x))

    if args.proof:
        if args.type == "wesolowski":
            ok = check_proof_of_time_wesolowski(
                discriminant, x, args.proof, args.iterations, args.length)
        elif args.type == "n-wesolowski":
           ok = check_proof_of_time_nwesolowski(
                discriminant, x, args.proof, args.iterations, args.length)
        elif args.type == "pietrzak":
            ok = check_proof_of_time_pietrzak(
                discriminant, x, args.proof, args.iterations, args.length)
        if ok:
            print("Proof is valid")
        else:
            print("** INVALID PROOF")
            return -1
    else:
        start_t = time.time() * 1000
        if args.type == "wesolowski":
            result, proof = create_proof_of_time_wesolowski(
                discriminant, x, args.iterations, args.length)
        elif args.type == "n-wesolowski":
            result, proof = create_proof_of_time_nwesolowski(
                discriminant, x, args.iterations, args.length, args.depth, 0)
        elif args.type == "pietrzak":
            result, proof = create_proof_of_time_pietrzak(
                discriminant, x, args.iterations, args.length)
        if args.verbose:
            print("Finished in ", round(((time.time() * 1000) - start_t), 2), "ms")
        ce = ClassgroupElement(result[0], result[1])
        print((ce.serialize() + proof).hex())


if __name__ == "__main__":
    main()

"""
Copyright 2018 Chia Network Inc

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
