import { useState, useEffect } from 'react';
import isContentHashValid from '../util/isContentHashValid';
import getRemoteFileContent from '../util/getRemoteFileContent';

export default function useVerifyURIHash(uri: string, hash: string): {
  isValid: boolean;
  isLoading: boolean;
  error?: Error;
} {
  const [isValid, setIsValid] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState();

  async function validateHash(uri: string, hash: string): Promise<void> {
    try {
      setError(undefined);
      setIsLoading(true);
      setIsValid(false);

      if (uri) {
        const content = await getRemoteFileContent(uri);
        const isHashValid = isContentHashValid(content, hash);
        if (!isHashValid) {
          throw new Error(`Hash mismatch`);
        }

        setIsValid(true);
      }
    } catch (e: any) {
      setError(e);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    validateHash(uri, hash);
  }, [uri, hash]);

  return { isValid, isLoading, error };
}
