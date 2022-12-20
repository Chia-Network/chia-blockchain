#!/bin/env python3


from pathlib import Path

import argparse
import os
import secrets
import time

import segno

from hsms.bls12_381 import BLSSecretExponent

import hsms.cmds.hsms


def wait_for_usb_mount(parser, mount_path, device_to_mount, mount_command_read_only):
    print(f"insert USB stick corresponding to {device_to_mount}")
    while 1:
        if device_to_mount.exists():
            cmd = mount_command_read_only.format(
                device_to_mount=device_to_mount, mount_path=mount_path
            )
            r = os.system(cmd)
            if r == 0:
                return
            parser.exit(1, f"failed to mount device {device_to_mount} read-only")
        time.sleep(1)


def generate_secret(wallet_path):
    CLEAR_SCREEN = "\033[2J"
    secret_exponent = BLSSecretExponent.from_int(secrets.randbits(256))
    b = secret_exponent.as_bech32m()
    assert BLSSecretExponent.from_bech32m(b) == secret_exponent

    print("No secret found. We are generating you a new secret.")
    while True:
        print(f"write down your secret:\n\n{b}\n")
        input("hit return when done> ")
        print(CLEAR_SCREEN)
        t = input("enter your secret> ")
        if t == b:
            break
        diff_string = "".join(" " if a1 == a2 else "^" for a1, a2 in zip(t, b))
        print(f"{b} <= actual secret")
        print(f"{t} <= you entered")
        print(diff_string)
        print("fix it and let's try again")
        print()

    with open(wallet_path, "w") as f:
        f.write(t)

    print(CLEAR_SCREEN)
    print("you entered your secret correctly! Good job")

    public_key = secret_exponent.public_key().as_bech32m()
    print(f"your public key is {public_key}")
    print("Take a photo of it and share with your coordinator:")
    qr = segno.make_qr(public_key)
    print()
    qr.terminal(compact=True)


def create_parser():
    parser = argparse.ArgumentParser(
        description="Wizard to look for USB mount point and key file and launch hsms"
    )
    parser.add_argument(
        "-d",
        "--device-to-mount",
        help="path, usually to something in `/dev/disk/` to ensure exists before attempting to mount",
    )
    parser.add_argument(
        "-r",
        "--mount-command-read-only",
        help="command to mount disk read-only",
        default="/usr/bin/sudo mount -o ro {device_to_mount} {mount_path}",
    )
    parser.add_argument(
        "-w",
        "--remount-command-read-write",
        help="command to remount disk read-write",
        default="/usr/bin/sudo mount -o remount,rw {device_to_mount} {mount_path}",
    )
    parser.add_argument(
        "-u",
        "--unmount-command",
        help="command to unmount disk",
        default="/usr/bin/sudo umount {mount_path}",
    )
    parser.add_argument(
        "path_to_secret_exponent_file",
        metavar="bech32m-encoded-se-file",
    )
    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    wallet_path = Path(args.path_to_secret_exponent_file)
    mount_path = wallet_path.parent
    if args.device_to_mount:
        wait_for_usb_mount(
            parser, mount_path, Path(args.device_to_mount), args.mount_command_read_only
        )
    if wallet_path.exists():
        parser = hsms.cmds.hsms.create_parser()
        args = parser.parse_args(["--qr", str(wallet_path)])
        hsms.cmds.hsms.hsms(args, parser)
    else:
        if args.remount_command_read_write:
            cmd = args.remount_command_read_write.format(
                device_to_mount=args.device_to_mount, mount_path=mount_path
            )
            r = os.system(cmd)
            if r != 0:
                parser.exit(
                    1, f"failed to remount device {args.device_to_mount} read/write"
                )
            cmd = f"/usr/bin/touch {wallet_path}.tmp && /bin/rm {wallet_path}.tmp"
            r = os.system(cmd)
            if r != 0:
                parser.exit(
                    1,
                    f"could not create temporary file `{wallet_path}.tmp`, drive permissions may be wrong",
                )
        generate_secret(wallet_path)
    print()
    input("hit return to power off> ")
    os.system("poweroff")


if __name__ == "__main__":
    main()
