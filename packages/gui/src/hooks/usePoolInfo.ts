import { useAsync } from 'react-use';
import isURL from 'validator/es/lib/isURL';
import { t } from '@lingui/macro';
import normalizeUrl from '../util/normalizeUrl';
import type PoolInfo from '../types/PoolInfo';
import useIsMainnet from './useIsMainnet';
import getPoolInfo from '../util/getPoolInfo';

export default function usePoolInfo(poolUrl?: string): {
  error?: Error;
  loading: boolean;
  poolInfo?: PoolInfo;
} {
  const isMainnet = useIsMainnet();

  const poolInfo = useAsync(async () => {
    if (isMainnet === undefined) {
      return undefined;
    }

    if (!poolUrl) {
      return undefined;
    }

    const isUrlOptions = {
      allow_underscores: true,
      require_valid_protocol: true,
    };

    if (isMainnet) {
      isUrlOptions.protocols = ['https'];
    }

    const normalizedUrl = normalizeUrl(poolUrl);
    const isValidUrl = isURL(normalizedUrl, isUrlOptions);

    if (!isValidUrl) {
      if (isMainnet && !normalizedUrl.startsWith('https:')) {
        throw new Error(
          t`The pool URL needs to use protocol https. ${normalizedUrl}`,
        );
      }

      throw new Error(t`The pool URL is not valid. ${normalizedUrl}`);
    }

    try {
      const data = await getPoolInfo(normalizedUrl);

      return {
        poolUrl: normalizedUrl,
        ...data,
      };
    } catch (e) {
      throw new Error(
        t`The pool URL "${normalizedUrl}" is not working. Is it pool? Error: ${e.message}`,
      );
    }
  }, [poolUrl, isMainnet]);

  return {
    error: poolInfo.error,
    loading: poolInfo.loading,
    poolInfo: poolInfo.value,
  };
}
