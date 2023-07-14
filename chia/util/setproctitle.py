from __future__ import annotations

try:
    import setproctitle as pysetproctitle

    no_setproctitle = False
except Exception:
    no_setproctitle = True


def setproctitle(ps_name: str) -> None:
    if no_setproctitle is False:
        pysetproctitle.setproctitle(ps_name)


def getproctitle() -> str:
    if no_setproctitle is False:
        return pysetproctitle.getproctitle()

    return ""
