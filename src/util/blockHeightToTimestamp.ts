import type Peak from "../types/Peak";

const BLOCK_DURATION_SECONDS = (24 * 60 * 60) / 4608;

export default function blockHeightToTimestamp(height: number, peak: Peak): number {
  const diff = peak.height - height;
  const seconds = diff * BLOCK_DURATION_SECONDS;

  /*
  console.log('peak', peak);
  console.log('height', height);
  console.log('diff', diff);
  console.log('seconds', seconds);
  */

  return peak.timestamp + seconds;
}
