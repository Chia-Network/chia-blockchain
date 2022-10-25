import logging
import pytest

from chia.util.errors import KeychainLabelError, KeychainLabelExists, KeychainFingerprintNotFound, KeychainLabelInvalid
from chia.util.keyring_wrapper import KeyringWrapper, DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
from pathlib import Path
from typing import Type
from sys import platform
from tests.util.keyring import using_temp_file_keyring, using_temp_file_keyring_and_cryptfilekeyring

log = logging.getLogger(__name__)


@pytest.fixture(autouse=True, scope="function")
def setup_keyring_wrapper():
    yield
    KeyringWrapper.cleanup_shared_instance()
    assert KeyringWrapper.get_shared_instance(create_if_necessary=False) is None


class TestKeyringWrapper:
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
    @using_temp_file_keyring_and_cryptfilekeyring()
    @pytest.mark.skip(reason="Does only work if `test_keyring_wrapper.py` gets called separately.")
    def test_using_legacy_cryptfilekeyring(self):
        """
        In the case that an existing CryptFileKeyring (legacy) keyring exists and we're
        creating a new FileKeyring, the legacy keyring's use should be prioritized over
        the FileKeyring (until migration is triggered by a write to the keyring.)
        """

        if platform != "linux":
            return

        # Expect: the new keyring should not have content (not actually empty though...)
        assert KeyringWrapper.get_shared_instance().keyring.has_content() is False
        assert Path(KeyringWrapper.get_shared_instance().keyring.keyring_path).exists() is True
        assert Path(KeyringWrapper.get_shared_instance().keyring.keyring_path).stat().st_size != 0

        # Expect: legacy keyring should be in use
        assert KeyringWrapper.get_shared_instance().legacy_keyring is not None
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is True
        assert KeyringWrapper.get_shared_instance().get_keyring() == KeyringWrapper.get_shared_instance().legacy_keyring

    # When: a file keyring has content and the legacy keyring exists
    @using_temp_file_keyring_and_cryptfilekeyring(populate=True)
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
    def test_file_keyring_supports_master_passphrase(self):
        """
        File keyrings should support setting a master passphrase
        """
        # Expect: keyring supports a master passphrase
        assert KeyringWrapper.get_shared_instance().keyring_supports_master_passphrase() is True

    # When: creating a new/unpopulated file keyring
    @using_temp_file_keyring()
    def test_empty_file_keyring_doesnt_have_master_passphrase(self):
        """
        A new/unpopulated file keyring should not have a master passphrase set
        """
        # Expect: no master passphrase set
        assert KeyringWrapper.get_shared_instance().has_master_passphrase() is False

    # When: using a populated file keyring
    @using_temp_file_keyring(populate=True)
    def test_populated_file_keyring_has_master_passphrase(self):
        """
        Populated keyring should have the default master passphrase set
        """
        # Expect: master passphrase is set
        assert KeyringWrapper.get_shared_instance().has_master_passphrase() is True

    # When: creating a new file keyring with a legacy keyring in place
    @pytest.mark.xfail(reason="wasn't running, fails now, to be removed soon")
    @using_temp_file_keyring_and_cryptfilekeyring()
    def test_legacy_keyring_does_not_support_master_passphrase(self):
        """
        CryptFileKeyring (legacy keyring) should not support setting a master passphrase
        """
        # Expect: legacy keyring in use and master passphrase is not supported
        assert KeyringWrapper.get_shared_instance().legacy_keyring is not None
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is True
        assert KeyringWrapper.get_shared_instance().keyring_supports_master_passphrase() is False

    # When: creating a new file keyring
    @using_temp_file_keyring()
    def test_default_cached_master_passphrase(self):
        """
        The default passphrase DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE is set
        """
        # Expect: cached passphrase set to DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE by default
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == (
            DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE,
            False,
        )
        assert KeyringWrapper.get_shared_instance().has_cached_master_passphrase() is True

    # When: using a file keyring
    @using_temp_file_keyring()
    def test_set_cached_master_passphrase(self):
        """
        Setting and retrieving the cached master passphrase should work
        """
        # When: setting the cached master passphrase
        KeyringWrapper.get_shared_instance().set_cached_master_passphrase("testing one two three")

        # Expect: cached passphrase should match
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == ("testing one two three", False)

        # When: setting a validated (successfully decrypted the content) master passphrase
        KeyringWrapper.get_shared_instance().set_cached_master_passphrase("apple banana orange grape", validated=True)

        # Expect: cached passphrase should match and be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == (
            "apple banana orange grape",
            True,
        )

    # When: using a populated file keyring
    @using_temp_file_keyring(populate=True)
    def test_master_passphrase_is_valid(self):
        """
        The default master passphrase should unlock the populated keyring (without any keys)
        """
        # Expect: default master passphrase should validate
        assert (
            KeyringWrapper.get_shared_instance().master_passphrase_is_valid(DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE)
            is True
        )

        # Expect: bogus passphrase should not validate
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("foobarbaz") is False

    # When: creating a new unpopulated keyring
    @using_temp_file_keyring()
    def test_set_master_passphrase_on_empty_keyring(self):
        """
        Setting a master passphrase should cache the passphrase and be usable to unlock
        the keyring. Using an old passphrase should not unlock the keyring.
        """
        # When: setting the master passphrase
        KeyringWrapper.get_shared_instance().set_master_passphrase(None, "testing one two three")

        # Expect: the master passphrase is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == ("testing one two three", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("testing one two three") is True

        # When: changing the master passphrase
        KeyringWrapper.get_shared_instance().set_master_passphrase("testing one two three", "potato potato potato")

        # Expect: the new master passphrase is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == ("potato potato potato", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("potato potato potato") is True

        # Expect: old passphrase should not validate
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("testing one two three") is False

    # When: using a populated keyring
    @using_temp_file_keyring(populate=True)
    def test_set_master_passphrase_on_keyring(self):
        """
        Setting a master passphrase should cache the passphrase and be usable to unlock
        the keyring. Using an old passphrase should not unlock the keyring.
        """
        # When: setting the master passphrase
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, "testing one two three"
        )

        # Expect: the master passphrase is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == ("testing one two three", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("testing one two three") is True

        # When: changing the master passphrase
        KeyringWrapper.get_shared_instance().set_master_passphrase("testing one two three", "potato potato potato")

        # Expect: the new master passphrase is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == ("potato potato potato", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("potato potato potato") is True

        # Expect: old passphrase should not validate
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("testing one two three") is False

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_remove_master_passphrase_from_empty_keyring(self):
        """
        An empty keyring doesn't require a current passphrase to remove the master passphrase.
        Removing the master passphrase will set the default master passphrase on the keyring.
        """
        # When: removing the master passphrase from an empty keyring, current passphrase isn't necessary
        KeyringWrapper.get_shared_instance().remove_master_passphrase(None)

        # Expect: default master passphrase is set
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == (
            DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE,
            True,
        )
        assert (
            KeyringWrapper.get_shared_instance().master_passphrase_is_valid(DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE)
            is True
        )

    # When: using a populated keyring
    @using_temp_file_keyring(populate=True)
    def test_remove_master_passphrase_from_populated_keyring(self):
        """
        A populated keyring will require a current passphrase when removing the master passphrase.
        Removing the master passphrase will set the default master passphrase on the keyring.
        """
        # When: the master passphrase is set
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, "It's dangerous to go alone, take this!"
        )

        # When: removing the master passphrase
        KeyringWrapper.get_shared_instance().remove_master_passphrase("It's dangerous to go alone, take this!")

        # Expect: default master passphrase is set, old passphrase doesn't validate
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == (
            DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE,
            True,
        )
        assert (
            KeyringWrapper.get_shared_instance().master_passphrase_is_valid(DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE)
            is True
        )
        assert (
            KeyringWrapper.get_shared_instance().master_passphrase_is_valid("It's dangerous to go alone, take this!")
            is False
        )

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_get_passphrase(self):
        """
        Simple passphrase setting and retrieval
        """
        # Expect: passphrase lookup should return None
        assert KeyringWrapper.get_shared_instance().get_passphrase("service-abc", "user-xyz") is None

        # When: setting a passphrase
        KeyringWrapper.get_shared_instance().set_passphrase(
            "service-abc", "user-xyz", "super secret passphrase".encode().hex()
        )

        # Expect: passphrase lookup should succeed
        assert (
            KeyringWrapper.get_shared_instance().get_passphrase("service-abc", "user-xyz")
            == "super secret passphrase".encode().hex()
        )

        # Expect: non-existent passphrase lookup should fail
        assert (
            KeyringWrapper.get_shared_instance().get_passphrase("service-123", "some non-existent passphrase") is None
        )

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_set_passphrase_overwrite(self):
        """
        Overwriting a previously-set passphrase should work
        """
        # When: initially setting the passphrase
        KeyringWrapper.get_shared_instance().set_passphrase(
            "service-xyz", "user-123", "initial passphrase".encode().hex()
        )

        # Expect: passphrase lookup should succeed
        assert (
            KeyringWrapper.get_shared_instance().get_passphrase("service-xyz", "user-123")
            == "initial passphrase".encode().hex()
        )

        # When: updating the same passphrase
        KeyringWrapper.get_shared_instance().set_passphrase(
            "service-xyz", "user-123", "updated passphrase".encode().hex()
        )

        # Expect: the updated passphrase should be retrieved
        assert (
            KeyringWrapper.get_shared_instance().get_passphrase("service-xyz", "user-123")
            == "updated passphrase".encode().hex()
        )

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_delete_passphrase(self):
        """
        Deleting a non-existent passphrase should fail gracefully (no exceptions)
        """
        # Expect: deleting a non-existent passphrase should fail gracefully
        KeyringWrapper.get_shared_instance().delete_passphrase("some service", "some user")

        # When: setting a passphrase
        KeyringWrapper.get_shared_instance().set_passphrase("some service", "some user", "500p3r 53cr37".encode().hex())

        # Expect: passphrase retrieval should succeed
        assert (
            KeyringWrapper.get_shared_instance().get_passphrase("some service", "some user")
            == "500p3r 53cr37".encode().hex()
        )

        # When: deleting the passphrase
        KeyringWrapper.get_shared_instance().delete_passphrase("some service", "some user")

        # Expect: passphrase retrieval should fail gracefully
        assert KeyringWrapper.get_shared_instance().get_passphrase("some service", "some user") is None

    @using_temp_file_keyring()
    def test_emoji_master_passphrase(self):
        """
        Emoji master passphrases should just work 😀
        """
        # When: setting a passphrase containing emojis
        KeyringWrapper.get_shared_instance().set_master_passphrase(None, "🥳🤩🤪🤯😎😝😀")

        # Expect: the master passphrase is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == ("🥳🤩🤪🤯😎😝😀", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("🥳🤩🤪🤯😎😝😀") is True

        # Expect: an invalid passphrase containing an emoji should fail validation
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() != ("🦄🦄🦄🦄🦄🦄🦄🦄", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("🦄🦄🦄🦄🦄🦄🦄🦄") is False

    @using_temp_file_keyring()
    def test_japanese_master_passphrase(self):
        """
        Non-ascii master passphrases should just work
        """
        # When: setting a passphrase containing non-ascii characters
        KeyringWrapper.get_shared_instance().set_master_passphrase(None, "私は幸せな農夫です")

        # Expect: the master passphrase is cached and can be validated
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() == ("私は幸せな農夫です", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("私は幸せな農夫です") is True

        # Expect: an invalid passphrase containing an non-ascii characters should fail validation
        assert KeyringWrapper.get_shared_instance().get_cached_master_passphrase() != ("私は幸せな農夫ではありません", True)
        assert KeyringWrapper.get_shared_instance().master_passphrase_is_valid("私は幸せな農夫ではありません") is False

    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_set_master_passphrase_with_hint(self):
        """
        Setting a passphrase hint at the same time as setting the passphrase
        """
        # When: setting the master passphrase with a hint
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            None, "new master passphrase", passphrase_hint="some passphrase hint"
        )

        # Expect: hint can be retrieved
        assert KeyringWrapper.get_shared_instance().get_master_passphrase_hint() == "some passphrase hint"

    @using_temp_file_keyring()
    def test_passphrase_hint(self):
        """
        Setting and retrieving the passphrase hint
        """
        # Expect: no hint set by default
        assert KeyringWrapper.get_shared_instance().get_master_passphrase_hint() is None

        # When: setting the passphrase hint while setting the master passphrase
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            None, "passphrase", passphrase_hint="rhymes with bassphrase"
        )

        # Expect: to retrieve the passphrase hint that was just set
        assert KeyringWrapper.get_shared_instance().get_master_passphrase_hint() == "rhymes with bassphrase"

        # When: writing the keyring again
        KeyringWrapper.get_shared_instance().keyring.write_keyring()

        # Expect: the hint is still set
        assert KeyringWrapper.get_shared_instance().get_master_passphrase_hint() == "rhymes with bassphrase"

    @using_temp_file_keyring()
    def test_passphrase_hint_removal(self):
        """
        Removing a passphrase hint
        """
        # When: setting the passphrase hint while setting the master passphrase
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            None, "12345", passphrase_hint="President Skroob's luggage combination"
        )

        # Expect: to retrieve the passphrase hint that was just set
        assert (
            KeyringWrapper.get_shared_instance().get_master_passphrase_hint()
            == "President Skroob's luggage combination"
        )

        # When: removing the passphrase hint
        KeyringWrapper.get_shared_instance().set_master_passphrase("12345", "12345", passphrase_hint=None)

        # Expect: passphrase hint has been removed
        assert KeyringWrapper.get_shared_instance().get_master_passphrase_hint() is None

    @using_temp_file_keyring()
    def test_passphrase_hint_update(self):
        """
        Updating a passphrase hint
        """
        # When: setting the passphrase hint while setting the master passphrase
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            None, "i like turtles", passphrase_hint="My deepest darkest secret"
        )

        # Expect: to retrieve the passphrase hint that was just set
        assert KeyringWrapper.get_shared_instance().get_master_passphrase_hint() == "My deepest darkest secret"

        # When: updating the passphrase hint
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            "i like turtles", "i like turtles", passphrase_hint="Something you wouldn't expect The Shredder to say"
        )

        # Expect: to retrieve the passphrase hint that was just set
        assert (
            KeyringWrapper.get_shared_instance().get_master_passphrase_hint()
            == "Something you wouldn't expect The Shredder to say"
        )

    @using_temp_file_keyring()
    def test_get_label(self):
        keyring_wrapper = KeyringWrapper.get_shared_instance()
        # label lookup for 1, 2, 3 should return None
        assert keyring_wrapper.get_label(1) is None
        assert keyring_wrapper.get_label(2) is None
        assert keyring_wrapper.get_label(3) is None

        # Set and validate a label for 1
        keyring_wrapper.set_label(1, "one")
        assert keyring_wrapper.get_label(1) == "one"

        # Set and validate a label for 3
        keyring_wrapper.set_label(3, "three")

        # And validate all match the expected values
        assert keyring_wrapper.get_label(1) == "one"
        assert keyring_wrapper.get_label(2) is None
        assert keyring_wrapper.get_label(3) == "three"

    @using_temp_file_keyring()
    def test_set_label(self):
        keyring_wrapper = KeyringWrapper.get_shared_instance()
        # Set and validate a label for 1
        keyring_wrapper.set_label(1, "one")
        assert keyring_wrapper.get_label(1) == "one"

        # Set and validate a label for 2
        keyring_wrapper.set_label(2, "two")
        assert keyring_wrapper.get_label(2) == "two"

        # Change the label of 2
        keyring_wrapper.set_label(2, "two!")
        assert keyring_wrapper.get_label(2) == "two!"
        # 1 should still have the same label
        assert keyring_wrapper.get_label(1) == "one"

        # Change the label of 2 again
        keyring_wrapper.set_label(2, "two!!")
        assert keyring_wrapper.get_label(2) == "two!!"
        # 1 should still have the same label
        assert keyring_wrapper.get_label(1) == "one"

        # Change the label of 1
        keyring_wrapper.set_label(1, "one!")
        assert keyring_wrapper.get_label(1) == "one!"
        # 2 should still have the same label
        assert keyring_wrapper.get_label(2) == "two!!"

    @pytest.mark.parametrize(
        "label",
        [
            "🥳🤩🤪🤯😎😝😀",
            "私は幸せな農夫です",
            "لتفاصيل لتكتشف حقيقة وأساس ت",
        ],
    )
    @using_temp_file_keyring()
    def test_set_special_labels(self, label: str):
        keyring_wrapper = KeyringWrapper.get_shared_instance()
        keyring_wrapper.set_label(1, label)
        assert keyring_wrapper.get_label(1) == label

    @pytest.mark.parametrize(
        "label, exception, message",
        [
            ("one", KeychainLabelExists, "label 'one' already exists for fingerprint '1"),
            ("", KeychainLabelInvalid, "label can't be empty or whitespace only"),
            ("   ", KeychainLabelInvalid, "label can't be empty or whitespace only"),
            ("a\nb", KeychainLabelInvalid, "label can't contain newline or tab"),
            ("a\tb", KeychainLabelInvalid, "label can't contain newline or tab"),
            ("a label ", KeychainLabelInvalid, "label can't contain leading or trailing whitespaces"),
            (" a label", KeychainLabelInvalid, "label can't contain leading or trailing whitespaces"),
            (" a label ", KeychainLabelInvalid, "label can't contain leading or trailing whitespaces"),
            ("  a label ", KeychainLabelInvalid, "label can't contain leading or trailing whitespaces"),
            ("a" * 66, KeychainLabelInvalid, "label exceeds max length: 66/65"),
            ("a" * 70, KeychainLabelInvalid, "label exceeds max length: 70/65"),
        ],
    )
    @using_temp_file_keyring()
    def test_set_label_failures(self, label: str, exception: Type[KeychainLabelError], message: str) -> None:
        keyring_wrapper = KeyringWrapper.get_shared_instance()
        keyring_wrapper.set_label(1, "one")
        with pytest.raises(exception, match=message) as e:
            keyring_wrapper.set_label(1, label)
        assert e.value.label == label
        if isinstance(e.value, KeychainLabelExists):
            assert e.value.label == "one"
            assert e.value.fingerprint == 1

    @using_temp_file_keyring()
    def test_delete_label(self) -> None:
        keyring_wrapper = KeyringWrapper.get_shared_instance()
        # Set labels for 1,2 and validate them
        keyring_wrapper.set_label(1, "one")
        keyring_wrapper.set_label(2, "two")
        assert keyring_wrapper.get_label(1) == "one"
        assert keyring_wrapper.get_label(2) == "two"
        # Remove the label of 1
        keyring_wrapper.delete_label(1)
        assert keyring_wrapper.get_label(1) is None
        assert keyring_wrapper.get_label(2) == "two"
        # Remove the label of 2
        keyring_wrapper.delete_label(2)
        assert keyring_wrapper.get_label(1) is None
        assert keyring_wrapper.get_label(2) is None
        # Make sure the deletion fails for 0-2
        for i in range(3):
            with pytest.raises(KeychainFingerprintNotFound) as e:
                keyring_wrapper.delete_label(i)
            assert e.value.fingerprint == i
