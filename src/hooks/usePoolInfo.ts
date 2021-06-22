import { useAsync } from 'react-use';
import isURL from 'validator/es/lib/isURL';
import { t } from '@lingui/macro';
import normalizeUrl from '../util/normalizeUrl';
import type PoolInfo from '../types/PoolInfo';

export default function usePoolInfo(poolUrl?: string): {
  error?: Error;
  loading: boolean;
  poolInfo?: PoolInfo;
} {
  const poolInfo = useAsync(async () => {
    if (!poolUrl) {
      return undefined;
    }

    const normalizedUrl = normalizeUrl(poolUrl);
    const isValidUrl = isURL(normalizedUrl, {
      allow_underscores: true,
    })

    if (!isValidUrl) {
      throw new Error(t`The pool URL speciefied is not valid. ${poolUrl}`);
    }

    try {
      const url = `${normalizedUrl}/pool_info`;
      const response = await fetch(url);
      const data = await response.json();

      return {
        pool_url: normalizedUrl,
        ...data,
      };
    } catch (e) {
      throw new Error(t`The pool URL "${normalizedUrl}" is not working. Is it pool? Error: ${e.message}`);
    }
  }, [poolUrl]);

  return {
    error: poolInfo.error,
    loading: poolInfo.loading,
    poolInfo: poolInfo.value,
  };
}
