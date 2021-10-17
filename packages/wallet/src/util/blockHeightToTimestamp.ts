import type Transaction from '../types/Transaction';

const BLOCK_DURATION_SECONDS = (24 * 60 * 60) / 4608;

export default function blockHeightToTimestamp(
  height: number,
  peakTransaction: Transaction,
): number {
  const diff = peakTransaction.confirmedAtHeight - height;
  const seconds = diff * BLOCK_DURATION_SECONDS;

  return peakTransaction.createdAtTime - seconds;
}
