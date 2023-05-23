from __future__ import annotations

import json
from pathlib import Path

from blspy import AugSchemeMPL, PublicKeyMPL, SignatureMPL

from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash


def validate_alert_file(file_path: Path, pubkey: str) -> bool:
    text = file_path.read_text()
    validated = validate_alert(text, pubkey)
    return validated


def validate_alert(text: str, pubkey: str) -> bool:
    json_obj = json.loads(text)
    data = json_obj["data"]
    message = bytes(data, "UTF-8")
    signature = json_obj["signature"]
    signature = SignatureMPL.from_bytes(hexstr_to_bytes(signature))
    pubkey_bls = PublicKeyMPL.from_bytes(hexstr_to_bytes(pubkey))
    sig_match_my = AugSchemeMPL.verify(pubkey_bls, message, signature)

    return sig_match_my


def create_alert_file(alert_file_path: Path, key, genesis_challenge_preimage: str):
    bytes_preimage = bytes(genesis_challenge_preimage, "UTF-8")
    genesis_challenge = std_hash(bytes_preimage)
    file_dict = {
        "ready": True,
        "genesis_challenge": genesis_challenge.hex(),
        "genesis_challenge_preimage": genesis_challenge_preimage,
    }
    data: str = json.dumps(file_dict)
    signature = AugSchemeMPL.sign(key, bytes(data, "utf-8"))
    file_data = {"data": data, "signature": f"{signature}"}
    file_data_json = json.dumps(file_data)
    alert_file_path.write_text(file_data_json)


def create_not_ready_alert_file(alert_file_path: Path, key):
    file_dict = {
        "ready": False,
    }
    data: str = json.dumps(file_dict)
    signature = AugSchemeMPL.sign(key, bytes(data, "utf-8"))
    file_data = {"data": data, "signature": f"{signature}"}
    file_data_json = json.dumps(file_data)
    alert_file_path.write_text(file_data_json)
