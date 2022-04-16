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
        />
        <SideBarItem
          to="/dashboard/nfts"
          icon={NFTsIcon}
          title={<Trans>NFTs</Trans>}
        />
        <SideBarItem
          to="/dashboard/offers"
          icon={OffersIcon}
          title={<Trans>Offers</Trans>}
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
              end
            />
            <SideBarItem
              to="/dashboard/plot"
              icon={PlotsIcon}
              title={<Trans>Plots</Trans>}
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
            />
            <SideBarItem
              to="/dashboard/pool"
              icon={PoolingIcon}
              title={<Trans>Pooling</Trans>}
            />
          </>
        )}
      </StyledItemsContainer>
      <StyledSettingsContainer>
        <SideBarItem
          to="/dashboard/settings"
          icon={SettingsIcon}
          title={<Trans>Settings</Trans>}
        />
      </StyledSettingsContainer>
    </StyledRoot>
  );
}
