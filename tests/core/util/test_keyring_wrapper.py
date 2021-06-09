import logging
import os
import tempfile
import unittest

from chia.util.file_keyring import FileKeyring
from chia.util.keyring_wrapper import KeyringWrapper, DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD
from keyring.util import platform_
from keyrings.cryptfile.cryptfile import CryptFileKeyring  # pyright: reportMissingImports=false
from pathlib import Path
from unittest.mock import patch

log = logging.getLogger(__name__)


def create_empty_cryptfilekeyring():
    """
    Create an empty legacy keyring
    """
    crypt_file_keyring = CryptFileKeyring()
    fd = os.open(crypt_file_keyring.file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)
    assert Path(crypt_file_keyring.file_path).exists()


def setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir, populate=False):
    if populate:
        # Populate the file keyring with an empty (but encrypted) data set
        file_keyring_path = FileKeyring.keyring_path_from_root(Path(temp_file_keyring_dir))
        os.makedirs(os.path.dirname(file_keyring_path), 0o775, False)
        with open(
            os.open(
                FileKeyring.keyring_path_from_root(Path(temp_file_keyring_dir)),
                os.O_CREAT | os.O_WRONLY | os.O_TRUNC,
                0o600,
            ),
            "w",
        ) as f:
            f.write(
                # Encrypted using DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD. Data holds an empty keyring.
                "data: Re+on6HbYfUm58bGVEfPoOwI+y2GrR1QUByZ8Qq8AgFnKc9tMnkk3ss=\n"
                "nonce: 41a01a265e74ad324b24cbe0\n"
                "salt: e1ca9b308dee7968e22a05bde98df3eb\n"
                "version: 1"
            )

    # Create the file keyring
    mock_configure_backend.return_value = FileKeyring(root_path=Path(temp_file_keyring_dir))


def using_temp_keyring_dir(func):
    """
    Decorator that will create a temporary keyring directory that is automatically
    cleaned-up after invoking the decorated function
    """

    def inner(*args, **kwargs):
        with tempfile.TemporaryDirectory(prefix="test_keyring_wrapper") as temp_file_keyring_dir:
            func(*args, **dict(kwargs, temp_file_keyring_dir=temp_file_keyring_dir))

    return inner


def using_temp_file_keyring(populate=False):
    def outer(func):
        @patch.object(KeyringWrapper, "_configure_backend")
        @using_temp_keyring_dir
        def inner(self, mock_configure_backend, temp_file_keyring_dir, *args, **kwargs):
            setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir, populate=populate)
            func(self, *args, **kwargs)

        return inner

    return outer


def using_temp_file_keyring_and_cryptfilekeyring(populate=False):
    def outer(func):
        @patch.object(KeyringWrapper, "_configure_backend")
        @patch.object(platform_, "data_root")
        @using_temp_keyring_dir
        def inner(self, mock_data_root, mock_configure_backend, temp_file_keyring_dir, *args, **kwargs):
            setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir)

            # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
            mock_data_root.return_value = temp_file_keyring_dir

            # Create an empty legacy keyring
            create_empty_cryptfilekeyring()

            func(self, *args, **kwargs)

        return inner

    return outer


class TestKeyringWrapper(unittest.TestCase):
    def setUp(self) -> None:
        return super().setUp()

    def tearDown(self) -> None:
        KeyringWrapper.cleanup_shared_instance()
        assert KeyringWrapper.get_shared_instance(create_if_necessary=False) is None
        return super().tearDown()

    def test_shared_instance(self):
        """
        Using KeyringWrapper's get_shared_instance() method should return the same
        instance each time it's called
        """
        # When: multiple calls to the shared accessor are made
        kw1 = KeyringWrapper.get_shared_instance()
        kw2 = KeyringWrapper.get_shared_instance()

        # Expect: the shared instance should exist
        assert kw1 is not None
        # Expect: multiple references should point to the same instance
        assert id(kw1) == id(kw2)

        # When: destroying the shared instance
        KeyringWrapper.cleanup_shared_instance()

        # Expect: the shared instance should be cleared
        assert KeyringWrapper.get_shared_instance(create_if_necessary=False) is None

    # When: creating a new file keyring with a legacy keyring in place
    @using_temp_file_keyring_and_cryptfilekeyring
    def test_using_legacy_keyring(self):
        """
        In the case that an existing CryptFileKeyring (legacy) keyring exists and we're
        creating a new FileKeyring, the legacy keyring's use should be prioritized over
        the FileKeyring (until migration is triggered by a write to the keyring.)
        """
        # Expect: the new keyring should not have content (not actually empty though...)
        assert KeyringWrapper.get_shared_instance().keyring.has_content() is False
        assert Path(KeyringWrapper.get_shared_instance().keyring.keyring_path).exists() is True
        assert Path(KeyringWrapper.get_shared_instance().keyring.keyring_path).stat().st_size != 0

        # Expect: legacy keyring should be in use
        assert KeyringWrapper.get_shared_instance().legacy_keyring is not None
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is True
        assert KeyringWrapper.get_shared_instance().get_keyring() == KeyringWrapper.get_shared_instance().legacy_keyring

    # When: a file keyring has content and the legacy keyring exists
    @using_temp_file_keyring_and_cryptfilekeyring
    def test_using_file_keyring_with_legacy_keyring(self):
        """
        In the case that an existing CryptFileKeyring (legacy) keyring exists and we're
        using a new FileKeyring with some keys in it, the FileKeyring's use should be
        used instead of the legacy keyring.
        """
        # Expect: the new keyring should have content
        assert KeyringWrapper.get_shared_instance().keyring.has_content() is True

        # Expect: the new keyring should be in use
        assert KeyringWrapper.get_shared_instance().legacy_keyring is None
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is False
        assert KeyringWrapper.get_shared_instance().get_keyring() == KeyringWrapper.get_shared_instance().keyring

    # When: a file keyring has content and the legacy keyring doesn't exists
    @using_temp_file_keyring(populate=True)
    def test_using_file_keyring_without_legacy_keyring(self):
        """
        In the case of a new installation (no legacy CryptFileKeyring) using a FileKeyring
        with some content, the legacy keyring should not be used.
        """
        # Expect: the new keyring should have content
        assert KeyringWrapper.get_shared_instance().keyring.has_content() is True

        # Expect: the new keyring should be in use
        assert KeyringWrapper.get_shared_instance().legacy_keyring is None
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is False
        assert KeyringWrapper.get_shared_instance().get_keyring() == KeyringWrapper.get_shared_instance().keyring

    # When: a file keyring is empty/unpopulated and the legacy keyring doesn't exists
    @using_temp_file_keyring()
    def test_using_new_file_keyring(self):
        """
        In the case of a new installation using a new FileKeyring, the legacy keyring
        should not be used.
        """
        # Expect: the new keyring should not have any content
        assert KeyringWrapper.get_shared_instance().keyring.has_content() is False

        # Expect: the new keyring should be in use
        assert KeyringWrapper.get_shared_instance().legacy_keyring is None
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is False
        assert KeyringWrapper.get_shared_instance().get_keyring() == KeyringWrapper.get_shared_instance().keyring

    # When: using a file keyring
    @using_temp_file_keyring()
    def test_file_keyring_supports_master_password(self):
        """
        File keyrings should support setting a master password
        """
        # Expect: keyring supports a master password
        assert KeyringWrapper.get_shared_instance().keyring_supports_master_password() is True

    # When: creating a new/unpopulated file keyring
    @using_temp_file_keyring()
    def test_empty_file_keyring_doesnt_have_master_password(self):
        """
        A new/unpopulated file keyring should not have a master password set
        """
        # Expect: no master password set
        assert KeyringWrapper.get_shared_instance().has_master_password() is False

    # When: using a populated file keyring
    @using_temp_file_keyring(populate=True)
    def test_populated_file_keyring_has_master_password(self):
        """
        Populated keyring should have the default master password set
        """
        # Expect: master password is set
        assert KeyringWrapper.get_shared_instance().has_master_password() is True

    # When: creating a new file keyring with a legacy keyring in place
    @using_temp_file_keyring_and_cryptfilekeyring()
    def test_legacy_keyring_does_not_support_master_password(self):
        """
        CryptFileKeyring (legacy keyring) should not support setting a master password
        """
        # Expect: legacy keyring in use and master password is not supported
        assert KeyringWrapper.get_shared_instance().legacy_keyring is not None
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is True
        assert KeyringWrapper.get_shared_instance().keyring_supports_master_password() is False

    # When: creating a new file keyring
    @using_temp_file_keyring()
    def test_default_cached_master_password(self):
        """
        The default password DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD is set
        """
        # Expect: cached password set to DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD by default
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == (
            DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD,
            False,
        )
        assert KeyringWrapper.get_shared_instance().has_cached_master_password() is True

    # When: using a file keyring
    @using_temp_file_keyring()
    def test_set_cached_master_password(self):
        """
        Setting and retrieving the cached master password should work
        """
        # When: setting the cached master password
        KeyringWrapper.get_shared_instance().set_cached_master_password("testing one two three")

        # Expect: cached password should match
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == ("testing one two three", False)

        # When: setting a validated (successfully decrypted the content) master password
        KeyringWrapper.get_shared_instance().set_cached_master_password("apple banana orange grape", validated=True)

        # Expect: cached password should match and be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == ("apple banana orange grape", True)

    # When: using a populated file keyring
    @using_temp_file_keyring(populate=True)
    def test_master_password_is_valid(self):
        """
        The default master password should unlock the populated keyring (without any keys)
        """
        # Expect: default master password should validate
        assert (
            KeyringWrapper.get_shared_instance().master_password_is_valid(DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD)
            is True
        )

        # Expect: bogus password should not validate
        assert KeyringWrapper.get_shared_instance().master_password_is_valid("foobarbaz") is False

    # When: creating a new unpopulated keyring
    @using_temp_file_keyring()
    def test_set_master_password_on_empty_keyring(self):
        """
        Setting a master password should cache the password and be usable to unlock
        the keyring. Using an old password should not unlock the keyring.
        """
        # When: setting the master password
        KeyringWrapper.get_shared_instance().set_master_password(None, "testing one two three")

        # Expect: the master password is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == ("testing one two three", True)
        assert KeyringWrapper.get_shared_instance().master_password_is_valid("testing one two three") is True

        # When: changing the master password
        KeyringWrapper.get_shared_instance().set_master_password("testing one two three", "potato potato potato")

        # Expect: the new master password is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == ("potato potato potato", True)
        assert KeyringWrapper.get_shared_instance().master_password_is_valid("potato potato potato") is True

        # Expect: old password should not validate
        assert KeyringWrapper.get_shared_instance().master_password_is_valid("testing one two three") is False

    # When: using a populated keyring
    @using_temp_file_keyring(populate=True)
    def test_set_master_password_on_keyring(self):
        """
        Setting a master password should cache the password and be usable to unlock
        the keyring. Using an old password should not unlock the keyring.
        """
        # When: setting the master password
        KeyringWrapper.get_shared_instance().set_master_password(
            DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD, "testing one two three"
        )

        # Expect: the master password is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == ("testing one two three", True)
        assert KeyringWrapper.get_shared_instance().master_password_is_valid("testing one two three") is True

        # When: changing the master password
        KeyringWrapper.get_shared_instance().set_master_password("testing one two three", "potato potato potato")

        # Expect: the new master password is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == ("potato potato potato", True)
        assert KeyringWrapper.get_shared_instance().master_password_is_valid("potato potato potato") is True

        # Expect: old password should not validate
        assert KeyringWrapper.get_shared_instance().master_password_is_valid("testing one two three") is False

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_remove_master_password_from_empty_keyring(self):
        """
        An empty keyring doesn't require a current password to remove the master password.
        Removing the master password will set the default master password on the keyring.
        """
        # When: removing the master password from an empty keyring, current password isn't necessary
        KeyringWrapper.get_shared_instance().remove_master_password(None)

        # Expect: default master password is set
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == (
            DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD,
            True,
        )
        assert (
            KeyringWrapper.get_shared_instance().master_password_is_valid(DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD)
            is True
        )

    # When: using a populated keyring
    @using_temp_file_keyring(populate=True)
    def test_remove_master_password_from_populated_keyring(self):
        """
        A populated keyring will require a current password when removing the master password.
        Removing the master password will set the default master password on the keyring.
        """
        # When: the master password is set
        KeyringWrapper.get_shared_instance().set_master_password(
            DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD, "It's dangerous to go alone, take this!"
        )

        # When: removing the master password
        KeyringWrapper.get_shared_instance().remove_master_password("It's dangerous to go alone, take this!")

        # Expect: default master password is set, old password doesn't validate
        assert KeyringWrapper.get_shared_instance().get_cached_master_password() == (
            DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD,
            True,
        )
        assert (
            KeyringWrapper.get_shared_instance().master_password_is_valid(DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD)
            is True
        )
        assert (
            KeyringWrapper.get_shared_instance().master_password_is_valid("It's dangerous to go alone, take this!")
            is False
        )
