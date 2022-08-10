import React from 'react';
import { Trans } from '@lingui/macro';
import { Routes, Route, useNavigate, useMatch } from 'react-router-dom';
import { Flex, LayoutDashboardSub } from '@chia/core';
import { Typography, Tab, Tabs } from '@mui/material';
import SettingsGeneral from './SettingsGeneral';
import SettingsProfiles from './SettingsProfiles';
import SettingsNFT from './SettingsNFT';

export default function Settings() {
  const navigate = useNavigate();
  const isGeneral = !!useMatch({ path: '/dashboard/settings', end: true });
  const isProfiles = !!useMatch('/dashboard/settings/profiles/*');

  console.log('isProfiles', isProfiles);

  const activeTab = isGeneral ? 'GENERAL' : isProfiles ? 'PROFILES' : 'NFT';

  function handleChangeTab(newTab: string) {
    if (newTab === 'PROFILES') {
      navigate('/dashboard/settings/profiles');
    } else if (newTab === 'NFT') {
      navigate('/dashboard/settings/nft');
    } else {
      navigate('/dashboard/settings');
    }
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
              value="GENERAL"
              label={<Trans>General</Trans>}
              style={{ width: '175px' }}
              data-testid="Settings-tab-general"
            />
            <Tab
              value="PROFILES"
              label={<Trans>Profiles</Trans>}
              style={{ width: '175px' }}
              data-testid="Settings-tab-profiles"
            />
            {/*
            <Tab
              value="NFT"
              label={<Trans>NFT</Trans>}
              style={{ width: '175px' }}
              data-testid="Settings-tab-nft"
            />
            */}
          </Tabs>

          <Routes>
            <Route path="profiles/*" element={<SettingsProfiles />} />
            <Route path="nft" element={<SettingsNFT />} />
            <Route index element={<SettingsGeneral />} />
          </Routes>
        </Flex>
      </Flex>
    </LayoutDashboardSub>
  );
}
