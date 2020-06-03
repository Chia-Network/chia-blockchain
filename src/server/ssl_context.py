import ssl

from pathlib import Path
from typing import Optional, Dict

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


def ssl_context_for_server(
    root_path: Path, config: Dict, require_cert: bool = False
) -> Optional[ssl.SSLContext]:
    paths = load_ssl_paths(root_path, config)
    if paths is None:
        return paths
    private_cert, private_key = paths
    ssl_context = ssl._create_unverified_context(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=private_cert, keyfile=private_key)
    ssl_context.load_verify_locations(private_cert)
    ssl_context.verify_mode = ssl.CERT_REQUIRED if require_cert else ssl.CERT_NONE
    return ssl_context


def ssl_context_for_client(
    root_path: Path, config: Dict, auth: bool
) -> Optional[ssl.SSLContext]:
    paths = load_ssl_paths(root_path, config)
    if paths is None:
        return paths
    private_cert, private_key = paths
    ssl_context = ssl._create_unverified_context(purpose=ssl.Purpose.SERVER_AUTH)
    ssl_context.load_cert_chain(certfile=private_cert, keyfile=private_key)
    if auth:
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.load_verify_locations(private_cert)
    else:
        ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context
