import React from 'react';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Flex, Link } from '@chia/core';
import LayoutMain from '../layout/LayoutMain';
import PoolOverview from './PoolOverview';
import PoolAdd from './add/PoolAdd';
import { PoolHeaderTarget }  from './PoolHeader';
import type { RootState } from '../../modules/rootReducer';

export default function Pool() {
  const { path } = useRouteMatch();

  const pools = useSelector((state: RootState) => state.pool_group.pools);
  const loading = !pools;

  return (
    <LayoutMain 
      title={
        <>
          <Link to="/dashboard/pool" color="textPrimary">
            <Trans>Pool</Trans>
          </Link>
          <PoolHeaderTarget />
        </>
      } 
      loading={loading}
    >
      <Flex flexDirection="column" gap={3}>
        <Switch>
          <Route path={path} exact>
            <PoolOverview />
          </Route>
          <Route path={`${path}/add`}>
            <PoolAdd />
          </Route>
        </Switch>
      </Flex>
    </LayoutMain>
  );
}
