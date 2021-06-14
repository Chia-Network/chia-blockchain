import React from 'react';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import { Flex, Link } from '@chia/core';
import LayoutMain from '../layout/LayoutMain';
import PoolOverview from './PoolOverview';
import GroupAdd from '../plotNFT/add/PlotNFTAdd';
import { PoolHeaderTarget }  from './PoolHeader';
import usePlotNFTs from '../../hooks/usePlotNFTs';
import { PoolHeaderSource } from './PoolHeader';

export default function Pool() {
  const { path } = useRouteMatch();
  const { nfts, loading } = usePlotNFTs();

  return (
    <LayoutMain
      loading={loading}
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
            <GroupAdd headerTag={PoolHeaderSource} />
          </Route>
        </Switch>
      </Flex>
    </LayoutMain>
  );
}
