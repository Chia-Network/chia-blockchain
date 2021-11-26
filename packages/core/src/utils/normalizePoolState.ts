import type { PoolState } from '@chia/api';
import removeOldPoints from './removeOldPoints';

export default function normalizePoolState(poolState: PoolState): PoolState {
  return {
    ...poolState,
    points_acknowledged_24h: removeOldPoints(poolState.points_acknowledged_24h),
    points_found_24h: removeOldPoints(poolState.points_found_24h),
  };
}
