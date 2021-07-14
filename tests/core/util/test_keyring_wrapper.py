import logging
import unittest

from chia.util.keyring_wrapper import KeyringWrapper, DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD
from pathlib import Path
from tests.util.keyring import using_temp_file_keyring, using_temp_file_keyring_and_cryptfilekeyring

log = logging.getLogger(__name__)


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

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_get_password(self):
        """
        Simple password setting and retrieval
        """
        # Expect: password lookup should return None
        assert KeyringWrapper.get_shared_instance().get_password("service-abc", "user-xyz") is None

        # When: setting a password
        KeyringWrapper.get_shared_instance().set_password("service-abc", "user-xyz", "super secret password".encode())

        # Expect: password lookup should succeed
        assert (
            KeyringWrapper.get_shared_instance().get_password("service-abc", "user-xyz")
            == "super secret password".encode().hex()
        )

        # Expect: non-existent password lookup should fail
        assert KeyringWrapper.get_shared_instance().get_password("service-123", "some non-existent password") is None

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_set_password_overwrite(self):
        """
        Overwriting a previously-set password should work
        """
        # When: initially setting the password
        KeyringWrapper.get_shared_instance().set_password("service-xyz", "user-123", "initial password".encode())

        # Expect: password lookup should succeed
        assert (
            KeyringWrapper.get_shared_instance().get_password("service-xyz", "user-123")
            == "initial password".encode().hex()
        )

        # When: updating the same password
        KeyringWrapper.get_shared_instance().set_password("service-xyz", "user-123", "updated password".encode())

        # Expect: the updated password should be retrieved
        assert (
            KeyringWrapper.get_shared_instance().get_password("service-xyz", "user-123")
            == "updated password".encode().hex()
        )

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_delete_password(self):
        """
        Deleting a non-existent password should fail gracefully (no exceptions)
        """
        # Expect: deleting a non-existent password should fail gracefully
        KeyringWrapper.get_shared_instance().delete_password("some service", "some user")

        # When: setting a password
        KeyringWrapper.get_shared_instance().set_password("some service", "some user", "500p3r 53cr37".encode())

        # Expect: password retrieval should succeed
        assert (
            KeyringWrapper.get_shared_instance().get_password("some service", "some user")
            == "500p3r 53cr37".encode().hex()
        )

        # When: deleting the password
        KeyringWrapper.get_shared_instance().delete_password("some service", "some user")

        # Expect: password retrieval should fail gracefully
        assert KeyringWrapper.get_shared_instance().get_password("some service", "some user") is None
