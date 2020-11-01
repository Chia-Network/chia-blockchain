from pathlib import Path
from typing import Dict

from src.util.config import config_path_for_filename


def load_ssl_paths(path: Path, config: Dict):
    try:
        return (
            config_path_for_filename(path, config["ssl"]["crt"]),
            config_path_for_filename(path, config["ssl"]["key"]),
        )
    except Exception:
        pass

    return None
