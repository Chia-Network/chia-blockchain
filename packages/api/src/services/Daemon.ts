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

  getKey(fingerprint: string, includeSecrets?: boolean) {
    return this.command('get_key', {
      fingerprint,
      includeSecrets,
    });
  }

  getKeys(includeSecrets?: boolean) {
    return this.command('get_keys', {
      includeSecrets,
    });
  }

  setLabel(fingerprint: string, label: string) {
    return this.command('set_label', {
      fingerprint,
      label,
    });
  }

  deleteLabel(fingerprint: string) {
    return this.command('delete_label', {
      fingerprint,
    });
  }

  keyringStatus() {
    return this.command('keyring_status');
  }

  setKeyringPassphrase(
    currentPassphrase?: string | null,
    newPassphrase?: string,
    passphraseHint?: string,
    savePassphrase?: boolean
  ) {
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

  migrateKeyring(
    passphrase: string,
    passphraseHint: string,
    savePassphrase: boolean,
    cleanupLegacyKeyring: boolean
  ) {
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

  getPlotters() {
    return this.command('get_plotters');
  }

  stopPlotting(id: string) {
    return this.command('stop_plotting', {
      id,
      service: ServiceName.PLOTTER,
    });
  }

  startPlotting(
    plotterName, // plotterName
    k, // plotSize
    n, // plotCount
    t, // workspaceLocation
    t2, // workspaceLocation2
    d, // finalLocation
    b, // maxRam
    u, // numBuckets
    r, // numThreads,
    queue, // queue
    a, // fingerprint
    parallel, // parallel
    delay, // delay
    e, // disableBitfieldPlotting
    x, // excludeFinalDir
    overrideK, //overrideK
    f, // farmerPublicKey
    p, // poolPublicKey
    c, // poolContractAddress
    bb_disable_numa, // bladebitDisableNUMA,
    bb_warm_start, // bladebitWarmStart,
    mm_v, // madmaxNumBucketsPhase3,
    mm_G, // madmaxTempToggle,
    mm_K, // madmaxThreadMultiplier,
  ) {
    const args = {
      service: ServiceName.PLOTTER,
      plotter: plotterName,
      k,
      n,
      t,
      t2,
      d,
      b,
      u,
      r,
      queue,
      parallel,
      delay,
      e,
      x,
      overrideK,
    };

    if (a) args.a = a;
    if (f) args.f = f;
    if (p) args.p = p;
    if (c) args.c = c;
    // bladebitDisableNUMA
    if (bb_disable_numa) args.m = bb_disable_numa;
    // bladebitWarmStart
    if (bb_warm_start) args.w = bb_warm_start;
    // madmaxNumBucketsPhase3
    if (mm_v) args.v = mm_v;
    // madmaxTempToggle
    if (mm_G) args.G = mm_G;
    // madmaxThreadMultiplier
    if (mm_K) args.K = mm_K;

    return this.command('start_plotting', args, undefined, undefined, true);
  }

  exit() {
    return this.command('exit');
  }

  onKeyringStatusChanged(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any
  ) {
    return this.onStateChanged('keyring_status_changed', callback, processData);
  }
}
