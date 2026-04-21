# Get the current authentication token according to "Farmer authentication" in SPECIFICATION.md
from __future__ import annotations

import datetime

import jwt
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8


def create_token(*, token_sk: str, plotnft_id: bytes32, current_time: datetime.datetime, expires_minutes: uint8) -> str:
    payload = {
        "sub": plotnft_id.hex(),
        "exp": current_time + datetime.timedelta(minutes=expires_minutes),
        "iat": current_time,
    }
    return jwt.encode(payload, token_sk, algorithm="HS256")


def verify_token(*, token_sk: str, token: str, plotnft_id: bytes32, current_time: datetime.datetime) -> bool:
    decoded = jwt.decode(token, token_sk, algorithms=["HS256"], options={"verify_exp": False})
    exp_time = datetime.datetime.fromtimestamp(decoded["exp"], tz=datetime.timezone.utc)
    return bytes32.from_hexstr(decoded["sub"]) == plotnft_id and exp_time >= current_time
