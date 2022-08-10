from chia.util.setproctitle import setproctitle


def test_does_not_crash():
    setproctitle("chia test title")
