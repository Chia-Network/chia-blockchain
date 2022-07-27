import React from 'react';
import { Trans } from '@lingui/macro';
import { Routes, Route, useNavigate, useMatch } from 'react-router-dom';
import { Flex, LayoutDashboardSub } from '@chia/core';
import { Typography, Tab, Tabs } from '@mui/material';
import SettingsGeneral from './SettingsGeneral';
import SettingsProfiles from './SettingsProfiles';


export default function Settings() {
  const navigate = useNavigate();
  const isGeneral = !!useMatch({ path: '/dashboard/settings', end: true });

  const activeTab = isGeneral ? 'GENERAL' : 'PROFILES';

  function handleChangeTab(newTab: string) {
    if (newTab === 'PROFILES') {
      navigate('/dashboard/settings/profiles');
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
            />
            <Tab
              value="PROFILES"
              label={<Trans>Profiles</Trans>}
              style={{ width: '175px' }}
            />
          </Tabs>

          <Routes>
            <Route path="profiles/*" element={<SettingsProfiles />} />
            <Route index element={<SettingsGeneral />} />
          </Routes>
        </Flex>
      </Flex>
    </LayoutDashboardSub>
  );
}
