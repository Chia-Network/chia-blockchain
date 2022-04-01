import React from 'react';
import { Trans } from '@lingui/macro';
import { Route, Routes } from 'react-router-dom';
import { Flex, Link, LayoutDashboardSub } from '@chia/core';
import PoolOverview from './PoolOverview';
import PlotNFTAdd from '../plotNFT/PlotNFTAdd';
import PlotNFTChangePool from '../plotNFT/PlotNFTChangePool';
import PlotNFTAbsorbRewards from '../plotNFT/PlotNFTAbsorbRewards';
import { PoolHeaderTarget } from './PoolHeader';
import { PoolHeaderSource } from './PoolHeader';

export default function Pool() {
  return (
    <LayoutDashboardSub>
      <Flex flexDirection="column" gap={3}>
        <Routes>
          <Route element={<PoolOverview />} index />
          <Route path="add" element={<PlotNFTAdd headerTag={PoolHeaderSource} />} />
          <Route path={`:plotNFTId/change-pool`} element={<PlotNFTChangePool headerTag={PoolHeaderSource} />} />
          <Route path={`:plotNFTId/absorb-rewards`} element={<PlotNFTAbsorbRewards headerTag={PoolHeaderSource} />} />
        </Routes>
      </Flex>
    </LayoutDashboardSub>
  );
}
