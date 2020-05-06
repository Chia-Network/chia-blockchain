try:
    import setproctitle as pysetproctitle

    no_setproctitle = False
except Exception:
    no_setproctitle = True


def setproctitle(ps_name):
    if no_setproctitle is False:
        pysetproctitle.setproctitle(ps_name)
