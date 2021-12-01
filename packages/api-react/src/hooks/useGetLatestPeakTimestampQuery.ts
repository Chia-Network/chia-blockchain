import { useRef, useMemo } from 'react';
import useGetLatestBlocksQuery from './useGetLatestBlocksQuery';

function getLatestTimestamp(
  blocks?: Object[],
  lastPeekTimestamp?: number,
): number | undefined {
  const timestamps = [];
  if (lastPeekTimestamp) {
    timestamps.push(lastPeekTimestamp);
  }

  if (blocks) {
    blocks.forEach(block => {
      if (block.timestamp) {
        timestamps.push(block.timestamp);
      }
    });
  }

  const timestampNumbers = timestamps.map((value) => {
    if (typeof value === 'string') {
      return Number.parseInt(value, 10);
    }

    return value;
  });

  return timestampNumbers.length 
    ? Math.max(...timestampNumbers) 
    : undefined;
}

export default function useGetLatestPeakTimestampQuery() {
  const latestPeakTimestamp = useRef<number|undefined>();
  const { data: blocks, isLoading, ...rest } = useGetLatestBlocksQuery(10);

  const newPeakTimestamp = useMemo(
    () => getLatestTimestamp(blocks, latestPeakTimestamp.current),
    [blocks, latestPeakTimestamp],
  );

  latestPeakTimestamp.current = newPeakTimestamp;

  return {
    isLoading,
    data: newPeakTimestamp,
    ...rest,
  };
}
