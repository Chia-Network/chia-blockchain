import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { Box } from '@mui/material';
import {
  Farming as FarmingIcon,
  FullNode as FullNodeIcon,
  Plots as PlotsIcon,
  Pooling as PoolingIcon,
  NFTs as NFTsIcon,
  Offers as OffersIcon,
  Tokens as TokensIcon,
  Settings as SettingsIcon,
} from '@chia/icons';
import { Flex, SideBarItem } from '@chia/core';

const StyledItemsContainer = styled(Flex)`
  flex-direction: column;
  flex-grow: 1;
  overflow: auto;
  padding-top: ${({ theme }) => `${theme.spacing(5)}`};
`;

const StyledRoot = styled(Flex)`
  height: 100%;
  flex-direction: column;
`;

const StyledSideBarDivider = styled(Box)`
  height: 1px;
  background: radial-gradient(
    36.59% 100.8% at 50% 50%,
    rgba(0, 0, 0, 0.18) 99.54%,
    rgba(255, 255, 255, 0) 100%
  );
`;

const StyledSettingsContainer = styled(Box)`
  background-color: ${({ theme }) => theme.palette.background.paper};
`;

export type DashboardSideBarProps = {
  simple?: boolean;
};

export default function DashboardSideBar(props: DashboardSideBarProps) {
  const { simple = false } = props;

  return (
    <StyledRoot>
      <StyledItemsContainer>
        <SideBarItem
          to="/dashboard/wallets"
          icon={TokensIcon}
          title={<Trans>Tokens</Trans>}
          data-testid="DashboardSideBar-tokens"
        />
        <SideBarItem
          to="/dashboard/nfts"
          icon={NFTsIcon}
          title={<Trans>NFTs</Trans>}
          data-testid="DashboardSideBar-nfts"
        />
        <SideBarItem
          to="/dashboard/offers"
          icon={OffersIcon}
          title={<Trans>Offers</Trans>}
          data-testid="DashboardSideBar-offers"
        />

        {!simple && (
          <>
            <Box my={1}>
              <StyledSideBarDivider />
            </Box>

            <SideBarItem
              to="/dashboard"
              icon={FullNodeIcon}
              title={<Trans>Full Node</Trans>}
              data-testid="DashboardSideBar-fullnode"
              end
            />
            <SideBarItem
              to="/dashboard/plot"
              icon={PlotsIcon}
              title={<Trans>Plots</Trans>}
              data-testid="DashboardSideBar-plots"
            />
            {/*}
            <SideBarItem
              to="/dashboard/wallets"
              icon={<WalletIcon fontSize="large" />}
              title={<Trans>Wallets</Trans>}
            />
            */}

            <SideBarItem
              to="/dashboard/farm"
              icon={FarmingIcon}
              title={<Trans>Farming</Trans>}
              data-testid="DashboardSideBar-farming"
            />
            <SideBarItem
              to="/dashboard/pool"
              icon={PoolingIcon}
              title={<Trans>Pooling</Trans>}
              data-testid="DashboardSideBar-pooling"
            />
          </>
        )}
      </StyledItemsContainer>
      <StyledSettingsContainer>
        <SideBarItem
          to="/dashboard/settings/general"
          icon={SettingsIcon}
          title={<Trans>Settings</Trans>}
          data-testid="DashboardSideBar-settings"
        />
      </StyledSettingsContainer>
    </StyledRoot>
  );
}
