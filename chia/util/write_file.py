import os
import shutil

from pathlib import Path
from typing import Union


def write_file(file_path: Path, data: Union[str, bytes], *, file_mode: int = 0o600):
    """
    Writes the provided data to a temporary file and then moves it to the final destination.
    """

    dir_perms: int = 0o700
    # Create the parent directory if necessary
    os.makedirs(os.path.dirname(file_path), mode=dir_perms, exist_ok=True)

    temp_path: Path = file_path.with_suffix("." + str(os.getpid()))
    mode: str = "w" if type(data) == str else "wb"
    with open(os.open(str(temp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, file_mode), mode) as f:
        f.write(data)
    try:
        os.replace(str(temp_path), file_path)
    except PermissionError:
        shutil.move(str(temp_path), str(file_path))
