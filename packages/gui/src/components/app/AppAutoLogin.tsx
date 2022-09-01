import React, { useEffect, type ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useUpdate } from 'react-use';
import { useNavigate } from 'react-router-dom';
import { useGetLoggedInFingerprintQuery } from '@chia/api-react';
import { LayoutLoading } from '@chia/core';
import useEnableAutoLogin from '../../hooks/useEnableAutoLogin';

export type AppAutoLoginProps = {
  children: ReactNode;
};

let isFingerprintReady = false;

export default function AppAutoLogin(props: AppAutoLoginProps) {
  const { children } = props;
  const update = useUpdate();
  const navigate = useNavigate();
  const [enableAutoLogin] = useEnableAutoLogin();
  const { data: fingerprint, isLoading } = useGetLoggedInFingerprintQuery();

  async function processFingerprint() {
    if (isLoading || isFingerprintReady) {
      return;
    }

    isFingerprintReady = true;

    if (fingerprint && enableAutoLogin) {
      navigate('/dashboard/wallets');
    }

    update();
  }

  useEffect(() => {
    processFingerprint();
  }, [isLoading, fingerprint]);

  if (!isFingerprintReady) {
    return (
      <LayoutLoading>
        <Trans>Loading fingerprint</Trans>
      </LayoutLoading>
    );
  }

  return <>{children}</>;
}
