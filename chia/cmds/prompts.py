from __future__ import annotations


def prompt_yes_no(prompt: str) -> bool:
    while True:
        response = str(input(prompt + " (y/n): ")).lower().strip()
        ch = response[:1]
        if ch == "y":
            return True
        elif ch == "n":
            return False
