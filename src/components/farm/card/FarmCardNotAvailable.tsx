import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { State, StateIndicator } from '@chia/core';
import FarmCard from './FarmCard';

type Props = {
  title: ReactNode;
  state?: State;
};

export default function FarmCardNotAvailable(props: Props) {
  const { title, state } = props;

  return (
    <FarmCard
      title={title}
      value={state ? (
        <StateIndicator state={state}>
          <Trans>Not Available</Trans>
        </StateIndicator>
      ) : (
        <Trans>Not Available</Trans>
      )}
      description={(
        <Trans>
          Wait for synchronization
        </Trans>
      )}
      valueColor="initial"
    />
  );
}
