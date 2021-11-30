import type Client from '../Client';
import Service from './Service';
import type { Options } from './Service';
import ServiceName from '../constants/ServiceName';

export default class Daemon extends Service {
  constructor(client: Client, options?: Options) {
    super(ServiceName.DAEMON, client, {
      skipAddService: true,
      ...options,
    });
  }

  registerService(service: string) {
    return this.command('register_service', {
      service,
    });
  }

  startService(service: string, testing?: boolean) {
    return this.command('start_service', {
      service,
      testing: testing ? true : undefined,
    });
  }

  stopService(service: string) {
    return this.command('stop_service', {
      service,
    });
  }

  isRunning(service: string) {
    return this.command('is_running', {
      service,
    });
  }

  keyringStatus() {
    return this.command('keyring_status');
  }

  setKeyringPassphrase(currentPassphrase?: string | null, newPassphrase?: string, passphraseHint?: string, savePassphrase?: boolean) {
    return this.command('set_keyring_passphrase', {
      currentPassphrase,
      newPassphrase,
      passphraseHint,
      savePassphrase,
    });
  }

  removeKeyringPassphrase(currentPassphrase: string) {
    return this.command('remove_keyring_passphrase', {
      currentPassphrase,
    });
  }

  migrateKeyring(passphrase: string, passphraseHint: string, savePassphrase: boolean, cleanupLegacyKeyring: boolean) {
    return this.command('migrate_keyring', {
      passphrase,
      passphraseHint,
      savePassphrase,
      cleanupLegacyKeyring,
    });
  }

  unlockKeyring(key: string) {
    return this.command('unlock_keyring', {
      key,
    });
  }

  exit() {
    return this.command('exit');
  }

  onKeyringStatusChanged(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onStateChanged('keyring_status_changed', callback, processData);
  }
}
