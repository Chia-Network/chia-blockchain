from filelock import FileLock


class LockingKeyring:
    """
    These operations may block.
    If another process dies, and leaves the lockfile, remove it.
    The Python-provided keyring is system-global, so it is important
    that the lockfile is also system-global
    """

    def __init__(self, lockfile, keyring):
        self.lockfile = lockfile
        self.keyring = keyring

    def get_password(self, service, username):
        with FileLock(self.lockfile):
            # print(f"get_password({self}, {service}, {username}) Lock acquired.")
            return self.keyring.get_password(service, username)

    def set_password(self, service, username, password):
        with FileLock(self.lockfile):
            # print(f"set_password({self}, {service}, {username}) Lock acquired.")
            return self.keyring.set_password(service, username, password)

    def delete_password(self, service, username):
        with FileLock(self.lockfile):
            # print(f"delete_password({self}, {service}, {username}) Lock acquired.")
            return self.keyring.delete_password(service, username)
