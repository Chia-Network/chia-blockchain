from .pip_import import pip_import


SETPROCTITLE_GITHUB = (
    "setproctitle @ "
    "https://github.com/Chia-Network/py-setproctitle/tarball/"
    "d2ed86c5080bb645d8f6b782a4a86706c860d9e6#egg=setproctitle-50.0.0"
)


def setproctitle(ps_name):
    pysetproctitle = pip_import("setproctitle", SETPROCTITLE_GITHUB)
    pysetproctitle.setproctitle(ps_name)
