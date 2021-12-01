import React from 'react';
import { Flex, Link, DashboardTitle } from '@chia/core';
import { Trans } from '@lingui/macro';
import { Route, Routes } from 'react-router-dom';
import PlotOverview from './overview/PlotOverview';
import PlotAdd from './add/PlotAdd';
import { PlotHeaderTarget } from './PlotHeader';

export default function Plot() {
  return (
    <>
      <DashboardTitle>
        <Link to="/dashboard/plot" color="textPrimary">
          <Trans>Plot</Trans>
        </Link>
        <PlotHeaderTarget />
      </DashboardTitle>
      <Flex flexDirection="column" gap={3}>
        <Routes>
          <Route index element={<PlotOverview />} />
          <Route path="add" element={<PlotAdd />} />
        </Routes>
      </Flex>
    </>
  );
}
