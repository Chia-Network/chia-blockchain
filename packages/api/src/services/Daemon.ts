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

  runningServices() {
    return this.command('running_services');
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
    plotterName: string, // plotterName
    k: number, // plotSize
    n: number, // plotCount
    t: string, // workspaceLocation
    t2: string, // workspaceLocation2
    d: string, // finalLocation
    b: number, // maxRam
    u: number, // numBuckets
    r: number, // numThreads,
    queue: string, // queue
    a: number | undefined, // fingerprint
    parallel: boolean, // parallel
    delay: number, // delay
    e?: boolean, // disableBitfieldPlotting
    x?: boolean, // excludeFinalDir
    overrideK?: boolean, //overrideK
    f?: string, // farmerPublicKey
    p?: string, // poolPublicKey
    c?: string, // poolContractAddress
    bb_disable_numa?: boolean, // bladebitDisableNUMA,
    bb_warm_start?: boolean, // bladebitWarmStart,
    mm_v?: number, // madmaxNumBucketsPhase3,
    mm_G?: boolean, // madmaxTempToggle,
    mm_K?: number, // madmaxThreadMultiplier,
    bb_no_cpu_affinity?: boolean, // bladebitNoCpuAffinity
    bb2_cache?: number, // bladebit2Cache
    bb2_f1_threads?: number, // bladebit2F1Threads
    bb2_fp_threads?: number, // bladebit2FpThreads
    bb2_c_threads?: number, // bladebit2CThreads
    bb2_p2_threads?: number, // bladebit2P2Threads
    bb2_p3_threads?: number, // bladebit2P3Threads
    bb2_alternate?: boolean, // bladebit2Alternate
    bb2_no_t1_direct?: boolean, // bladebit2NoT1Direct
    bb2_no_t2_direct?: boolean // bladebit2NoT2Direct
  ) {
    const args: Record<string, unknown> = {
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
    // bladebitNoCpuAffinity
    if (bb_no_cpu_affinity) args.no_cpu_affinity = bb_no_cpu_affinity;
    // bladebit2Cache
    if (bb2_cache) args.cache = `${bb2_cache}G`;
    // bladebit2F1Threads
    if (bb2_f1_threads) args.f1_threads = bb2_f1_threads;
    // bladebit2FpThreads
    if (bb2_fp_threads) args.fp_threads = bb2_fp_threads;
    // bladebit2CThreads
    if (bb2_c_threads) args.c_threads = bb2_c_threads;
    // bladebit2P2Threads
    if (bb2_p2_threads) args.p2_threads = bb2_p2_threads;
    // bladebit2P3Threads
    if (bb2_p3_threads) args.p3_threads = bb2_p3_threads;
    // bladebit2Alternate
    if (bb2_alternate) args.alternate = bb2_alternate;
    // bladebit2NoT1Direct
    if (bb2_no_t1_direct) args.no_t1_direct = bb2_no_t1_direct;
    // bladebit2NoT2Direct
    if (bb2_no_t2_direct) args.no_t2_direct = bb2_no_t2_direct;

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
