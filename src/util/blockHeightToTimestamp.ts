import type Peak from '../types/Peak';

const BLOCK_DURATION_SECONDS = (24 * 60 * 60) / 4608;

export default function blockHeightToTimestamp(
  height: number,
  peak: Peak,
): number {
  const diff = peak.height - height;
  const seconds = diff * BLOCK_DURATION_SECONDS;

  return peak.timestamp - seconds;
}
