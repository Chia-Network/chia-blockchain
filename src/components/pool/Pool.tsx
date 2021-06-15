import React from 'react';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import { Flex, Link } from '@chia/core';
import LayoutMain from '../layout/LayoutMain';
import PoolOverview from './PoolOverview';
import PlotNFTAdd from '../plotNFT/PlotNFTAdd';
import PlotNFTChangePool from '../plotNFT/PlotNFTChangePool';
import { PoolHeaderTarget }  from './PoolHeader';
import usePlotNFTs from '../../hooks/usePlotNFTs';
import { PoolHeaderSource } from './PoolHeader';

export default function Pool() {
  const { path } = useRouteMatch();
  const { loading } = usePlotNFTs();

  return (
    <LayoutMain
      loading={loading}
      loadingTitle={<Trans>Loading Plot NFTs</Trans>}
      title={
        <>
          <Link to="/dashboard/pool" color="textPrimary">
            <Trans>Pool</Trans>
          </Link>
          <PoolHeaderTarget />
        </>
      }
    >
      <Flex flexDirection="column" gap={3}>
        <Switch>
          <Route path={path} exact>
            <PoolOverview />
          </Route>
          <Route path={`${path}/add`}>
            <PlotNFTAdd headerTag={PoolHeaderSource} />
          </Route>
          <Route path={`${path}/:plotNFTId/change-pool`}>
            <PlotNFTChangePool headerTag={PoolHeaderSource} />
          </Route>
        </Switch>
      </Flex>
    </LayoutMain>
  );
}
