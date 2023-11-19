from __future__ import annotations

from setuptools_scm import get_version


# example: 1.0b5.dev225
def main() -> None:
    scm_full_version = get_version(root="..", relative_to=__file__)
    # scm_full_version = "1.0.5.dev22"

    left_full_version = scm_full_version.split("+")
    version = left_full_version[0].split(".")
    scm_major_version = version[0]
    scm_minor_version = version[1]

    if len(version) == 3:  # If the length of the version array is more than 2
        patch_release_number = version[2]
        scm_patch_version = patch_release_number
        dev_release_number = ""
    elif len(version) == 4:
        scm_patch_version = version[2]
        dev_release_number = "-" + version[3]
    else:
        scm_patch_version = ""
        dev_release_number = ""

    major_release_number = scm_major_version
    minor_release_number = scm_minor_version

    # If this is a beta dev release, get which beta it is
    if "0b" in scm_minor_version:
        orignial_minor_ver_list = scm_minor_version.split("0b")
        major_release_number = str(1 - int(scm_major_version))  # decrement the major release for beta
        minor_release_number = scm_major_version
        patch_release_number = orignial_minor_ver_list[1]
        if scm_patch_version and "dev" in scm_patch_version:
            dev_release_number = "." + scm_patch_version
    elif "0rc" in version[1]:
        original_minor_ver_list = scm_minor_version.split("0rc")
        major_release_number = str(1 - int(scm_major_version))  # decrement the major release for release candidate
        minor_release_number = str(int(scm_major_version) + 1)  # RC is 0.2.1 for RC 1
        patch_release_number = original_minor_ver_list[1]
        if scm_patch_version and "dev" in scm_patch_version:
            dev_release_number = "." + scm_patch_version
    elif len(version) == 2:
        patch_release_number = "0"
    elif len(version) == 4:  # for 1.0.5.dev2
        patch_release_number = scm_patch_version
    else:
        major_release_number = scm_major_version
        minor_release_number = scm_minor_version
        patch_release_number = scm_patch_version
        dev_release_number = ""

    install_release_number = major_release_number + "." + minor_release_number
    if len(patch_release_number) > 0:
        install_release_number += "." + patch_release_number
    if len(dev_release_number) > 0:
        install_release_number += dev_release_number

    print(str(install_release_number))


if __name__ == "__main__":
    main()
