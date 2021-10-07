from pathlib import Path


def db_synchronous_on(setting: str, db_path: Path) -> bool:
    if setting == "on":
        return True
    if setting == "off":
        return False

    # for now, default to synchronous=NORMAL mode. This can be made more
    # sophisticated in the future. There are still material performance
    # improvements to be had in cases where the risks are low.

    # e.g.
    # type = GetDriveTypeW(db_path)
    # if type == DRIVE_FIXED or type == DRIVE_RAMDISK:
    #     return False

    return True
