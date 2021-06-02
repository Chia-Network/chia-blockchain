import { useMemo } from 'react';
import { useAsync } from 'react-use';
import isURL from 'validator/es/lib/isURL';
import { t } from '@lingui/macro';
import type PoolInfo from '../types/PoolInfo';

export default function usePoolInfo(poolUrl?: string): {
  error?: Error;
  loading: boolean;
  poolInfo?: PoolInfo;
} {
  const isValidUrl = useMemo(() => !!poolUrl && isURL(poolUrl), [poolUrl]);

  const poolInfo = useAsync(async () => {
    if (!poolUrl) {
      return undefined;
    }

    if (!isValidUrl) {
      throw new Error(t`The pool URL speciefied is not valid. ${poolUrl}`);
    }

    const url = `${poolUrl}/pool_info`;
    const response = await fetch(url);
    const data = await response.json();

    return {
      pool_url: poolUrl,
      ...data,
    };
  }, [poolUrl]);

  return {
    error: poolInfo.error,
    loading: poolInfo.loading,
    poolInfo: poolInfo.value,
  };
}
