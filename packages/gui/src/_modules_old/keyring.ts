export type KeyringState = {
  is_locked: boolean;
  passphrase_support_enabled: boolean;
  can_save_passphrase: boolean;
  user_passphrase_set: boolean;
  needs_migration: boolean;
  can_remove_legacy_keys: boolean;
  migration_in_progress: boolean;
  migration_skipped: boolean;
  allow_empty_passphrase: boolean;
  min_passphrase_length: number;
  can_set_passphrase_hint: boolean;
  passphrase_hint: string;
};

const initialState: KeyringState = {
  is_locked: false,
  passphrase_support_enabled: false,
  can_save_passphrase: false,
  user_passphrase_set: false,
  needs_migration: false,
  can_remove_legacy_keys: false,
  migration_in_progress: false,
  migration_skipped: false,
  allow_empty_passphrase: false,
  min_passphrase_length: 0,
  can_set_passphrase_hint: false,
  passphrase_hint: "",
};

export default function keyringReducer(
  state = { ...initialState },
  action: any
): KeyringState {
  switch (action.type) {
    case 'SKIP_KEYRING_MIGRATION':
      return {
        ...state,
        migration_skipped: action.skip,
      };
    case 'INCOMING_MESSAGE':
      const { message } = action;
      const { data } = message;
      const { command } = message;
      if ((command === 'keyring_status') || (command === 'keyring_status_changed')) {
        if (data.success) {
          const {
            is_keyring_locked,
            passphrase_support_enabled,
            can_save_passphrase,
            user_passphrase_is_set,
            needs_migration,
            can_remove_legacy_keys,
            passphrase_requirements,
            can_set_passphrase_hint,
            passphrase_hint,
          } = data;
          const allow_empty_passphrase = passphrase_requirements?.is_optional || false;
          const min_passphrase_length = passphrase_requirements?.min_length || 10;
          return {
            ...state,
            is_locked: is_keyring_locked,
            passphrase_support_enabled: passphrase_support_enabled,
            can_save_passphrase: can_save_passphrase,
            user_passphrase_set: user_passphrase_is_set,
            needs_migration: needs_migration,
            can_remove_legacy_keys: can_remove_legacy_keys,
            allow_empty_passphrase: allow_empty_passphrase,
            min_passphrase_length: min_passphrase_length,
            can_set_passphrase_hint: can_set_passphrase_hint,
            passphrase_hint: passphrase_hint,
          };
        }
      } else if (command === 'unlock_keyring') {
        if (data.success) {
          return {
            ...state,
            is_locked: false,
          };
        }
        else {
          console.log("Failed to unlock keyring: " + data.error);
        }
      } else if (command === 'migrate_keyring') {
        // Clear the migration_in_progress flag
        state = {
          ...state,
          migration_in_progress: false
        };
        if (data.success) {
          return {
            ...state,
            needs_migration: false,
          };
        } else {
          console.log("Failed to migrate keyring: " + data.error);
        }
      }
      return state;
    case 'OUTGOING_MESSAGE':
      if (
        action.message.command === 'migrate_keyring' &&
        action.message.destination === 'daemon'
      ) {
        // Set a flag indicating that we're attempting to migrate the keyring
        return {
          ...state,
          migration_in_progress: true
        };
      }
      return state;
    default:
      return state;
  }
}
