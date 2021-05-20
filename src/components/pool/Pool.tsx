import React from 'react';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Flex, Link } from '@chia/core';
import LayoutMain from '../layout/LayoutMain';
import PoolOverview from './PoolOverview';
import GroupAdd from '../group/add/GroupAdd';
import { PoolHeaderTarget }  from './PoolHeader';
import type { RootState } from '../../modules/rootReducer';
import { PoolHeaderSource } from './PoolHeader';

export default function Pool() {
  const { path } = useRouteMatch();

  const groups = useSelector((state: RootState) => state.group.groups);
  const loading = !groups;

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
            <GroupAdd headerTag={PoolHeaderSource} />
          </Route>
        </Switch>
      </Flex>
    </LayoutMain>
  );
}
