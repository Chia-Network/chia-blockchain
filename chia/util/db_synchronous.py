from __future__ import annotations


def db_synchronous_on(setting: str) -> str:
    if setting == "on":
        return "NORMAL"
    if setting == "off":
        return "OFF"
    if setting == "full":
        return "FULL"

    # for now, default to synchronous=NORMAL mode. This can be made more
    # sophisticated in the future. There are still material performance
    # improvements to be had in cases where the risks are low.

    # e.g.
    # type = GetDriveTypeW(db_path)
    # if type == DRIVE_FIXED or type == DRIVE_RAMDISK:
    #     return "OFF"

    return "NORMAL"
