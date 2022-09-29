import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Routes,
  Route,
  matchPath,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import { Flex, LayoutDashboardSub } from '@chia/core';
import { Typography, Tab, Tabs } from '@mui/material';
import SettingsDataLayer from './SettingsDataLayer';
import SettingsGeneral from './SettingsGeneral';
import SettingsProfiles from './SettingsProfiles';
import SettingsNFT from './SettingsNFT';

enum SettingsTab {
  GENERAL = 'general',
  PROFILES = 'profiles',
  NFT = 'nft',
  DATALAYER = 'datalayer',
}

const SettingsTabsPathMapping = {
  [SettingsTab.GENERAL]: '/dashboard/settings/general',
  [SettingsTab.PROFILES]: '/dashboard/settings/profiles',
  [SettingsTab.NFT]: '/dashboard/settings/nft',
  [SettingsTab.DATALAYER]: '/dashboard/settings/datalayer',
};

export default function Settings() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const mapping = {
    ...SettingsTabsPathMapping,
    [SettingsTab.PROFILES]: '/dashboard/settings/profiles/*',
  };

  const activeTab =
    Object.entries(mapping).find(
      ([, pattern]) => !!matchPath(pattern, pathname),
    )?.[0] ?? SettingsTab.GENERAL;

  function handleChangeTab(newTab: SettingsTab) {
    const path =
      SettingsTabsPathMapping[newTab] ??
      SettingsTabsPathMapping[SettingsTab.GENERAL];
    navigate(path);
  }

  return (
    <LayoutDashboardSub>
      <Flex flexDirection="column" gap={3}>
        <Typography variant="h5">
          <Trans>Settings</Trans>
        </Typography>
        <Flex gap={3} flexDirection="column">
          <Tabs
            value={activeTab}
            onChange={(_event, newValue) => handleChangeTab(newValue)}
            textColor="primary"
            indicatorColor="primary"
          >
            <Tab
              value={SettingsTab.GENERAL}
              label={<Trans>General</Trans>}
              style={{ width: '175px' }}
              data-testid="Settings-tab-general"
            />
            <Tab
              value={SettingsTab.PROFILES}
              label={<Trans>Profiles</Trans>}
              style={{ width: '175px' }}
              data-testid="Settings-tab-profiles"
            />

            <Tab
              value={SettingsTab.NFT}
              label={<Trans>NFT</Trans>}
              style={{ width: '175px' }}
              data-testid="Settings-tab-nft"
            />

            <Tab
              value={SettingsTab.DATALAYER}
              label={<Trans>DataLayer</Trans>}
              style={{ width: '175px' }}
              data-testid="Settings-tab-datalayer"
            />
          </Tabs>

          <Routes>
            <Route path="profiles/*" element={<SettingsProfiles />} />
            <Route path="nft" element={<SettingsNFT />} />
            <Route path="datalayer" element={<SettingsDataLayer />} />
            <Route path="general" element={<SettingsGeneral />} />
          </Routes>
        </Flex>
      </Flex>
    </LayoutDashboardSub>
  );
}
