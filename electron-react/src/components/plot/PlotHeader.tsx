import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { useDispatch } from 'react-redux';
import { useHistory } from 'react-router-dom';
import { Button } from '@material-ui/core';
import { NavigateNext as NavigateNextIcon, Add as AddIcon } from '@material-ui/icons';
import RefreshIcon from '@material-ui/icons/Refresh';
import {
  refreshPlots,
} from '../../modules/harvesterMessages';

export default function PlotHeader() {
  const history = useHistory();
  const dispatch = useDispatch();

  function handleRefreshPlots() {
    dispatch(refreshPlots());
  }

  function handleAddPlot() {
    history.push('/dashboard/plot/add');
  }

  return (
    <div>
      <Flex alignItems="center">
        <Flex flexGrow={1}>
        </Flex>
        <div>
          <Button
            color="secondary"
            onClick={handleRefreshPlots}
            startIcon={<RefreshIcon />}
          >
            <Trans id="PlotHeader.refreshPlots">Refresh Plots</Trans>
          </Button>
          {' '}
          <Button color="primary" onClick={handleAddPlot} startIcon={<AddIcon />}>
            <Trans id="PlotHeader.addAPlot">Add a Plot</Trans>
          </Button>
        </div>
      </Flex>
    </div>
  );
}
