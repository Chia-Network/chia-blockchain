import React from 'react';
import { Trans } from '@lingui/macro';
import { AdvancedOptions, Flex } from '@chia/core';
import LayoutMain from '../layout/LayoutMain';
import FarmOverview from './overview/FarmOverview';
import FarmLatestBlockChallenges from './FarmLatestBlockChallenges';
import FarmFullNodeConnections from './FarmFullNodeConnections';
import FarmYourHarvesterNetwork from './FarmYourHarvesterNetwork';
import FarmLastAttemptedProof from './FarmLastAttemptedProof';
import usePlots from '../../hooks/usePlots';

export default function Farm() {
  const { hasPlots } = usePlots();

  return (
    <LayoutMain title={<Trans>Farming</Trans>}>
      <Flex flexDirection="column" gap={3}>
        <FarmOverview />

        <FarmLatestBlockChallenges />

        {hasPlots && (
          <>
            <FarmLastAttemptedProof />
            <AdvancedOptions>
              <Flex flexDirection="column" gap={3}>
                <FarmFullNodeConnections />
                <FarmYourHarvesterNetwork />
              </Flex>
            </AdvancedOptions>
          </>
        )}
      </Flex>
    </LayoutMain>
  );
}
