import React from 'react';
import { Trans } from '@lingui/macro';
import { AdvancedOptions, Flex, LayoutDashboardSub, Loading } from '@chia/core';
import { useGetHarvesterConnectionsQuery, useGetTotalHarvestersSummaryQuery } from '@chia/api-react';
import FarmHeader from './FarmHeader';
import FarmLatestBlockChallenges from './FarmLatestBlockChallenges';
import FarmFullNodeConnections from './FarmFullNodeConnections';
import FarmYourHarvesterNetwork from './FarmYourHarvesterNetwork';
import FarmLastAttemptedProof from './FarmLastAttemptedProof';
import FarmCards from './card/FarmCards';
import FarmHero from './FarmHero';

export default function Farm() {
  const { hasPlots, initialized, isLoading } = useGetTotalHarvestersSummaryQuery();
  const { data: connections } = useGetHarvesterConnectionsQuery();

  const showLoading = isLoading || (!hasPlots && !initialized);

  return (
    <LayoutDashboardSub>
      <Flex flexDirection="column" gap={2}>
        {showLoading ? (
          <Loading center>
            <Trans>Loading farming data</Trans>
          </Loading>
        ) : hasPlots ? (
          <>
            <FarmHeader />
            <Flex flexDirection="column" gap={4}>
              <FarmCards />
              <FarmLastAttemptedProof />
              <FarmLatestBlockChallenges />
              <AdvancedOptions>
                <Flex flexDirection="column" gap={3}>
                  <FarmFullNodeConnections />
                  <FarmYourHarvesterNetwork />
                </Flex>
              </AdvancedOptions>
            </Flex>
          </>
        ) : (
          <>
            <FarmHeader />
            <Flex flexDirection="column" gap={4}>
              <FarmHero />
              <FarmLatestBlockChallenges />
              {!!connections && (
                <AdvancedOptions>
                  <Flex flexDirection="column" gap={3}>
                    <FarmYourHarvesterNetwork />
                  </Flex>
                </AdvancedOptions>
              )}
            </Flex>
          </>
        )}
      </Flex>
    </LayoutDashboardSub>
  );
}
