import React, { type ReactNode, useMemo } from 'react';
import { Typography } from '@material-ui/core';
import { Trans } from '@lingui/macro';
import { useGetLoggedInFingerprintQuery } from '@chia/api-react';
import Flex from '../Flex';
import { createTeleporter } from 'react-teleporter';

const DashboardTitleTeleporter = createTeleporter();

export function DashboardTitleTarget() {
  return (
    <Typography component="h1" variant="h6" noWrap>
      <DashboardTitleTeleporter.Target />
    </Typography>
  );
}

type Props = {
  children?: ReactNode;
};

export default function DashboardTitle(props: Props) {
  const { data: fingerprint } = useGetLoggedInFingerprintQuery();
  const partial = useMemo(() => {
    if (fingerprint) {
      // return last 6 digits of fingerprint
      return `(...${fingerprint.toString().slice(-6)})`;
    }

    return null;
  }, [fingerprint]);

  return (
    <DashboardTitleTeleporter.Source>
      <Typography variant="h4">
        <Trans>
          Wallet
        </Trans>
        &nbsp;
        {partial}
      </Typography>
    </DashboardTitleTeleporter.Source>
  );
}

DashboardTitle.defaultProps = {
  children: undefined,
};
