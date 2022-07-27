import React, { useEffect, useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { IconButton, Typography } from '@mui/material';
import { Flex } from '@chia/core';
import { Route, Routes, useNavigate } from 'react-router-dom';
import IdentitiesPanel from './IdentitiesPanel';
import { LayoutDashboardSub } from '@chia/core';
import ProfileView from './ProfileView';
import ProfileAdd from './ProfileAdd';
import { Add } from '@mui/icons-material';
import { useGetWalletsQuery } from '@chia/api-react';
import { WalletType } from '@chia/api';

export default function SettingsProfiles() {
  const navigate = useNavigate();
  const { data: wallets } = useGetWalletsQuery();

  const didList = useMemo(() => {
    const dids: number[] = [];
    if (wallets) {
      wallets.forEach((wallet) => {
        if (wallet.type === WalletType.DECENTRALIZED_ID) {
          dids.push(wallet.id);
        }
      });
    }
    return dids;
  }, [wallets]);

  useEffect(() => {
    if (didList.length) {
      navigate(`/dashboard/settings/profiles/${didList[0]}`);
    } else {
      navigate(`/dashboard/settings/profiles/add`);
    }
  }, [didList]);

  function navAdd() {
    navigate(`/dashboard/settings/profiles/add`);
  }

  return (
    <div>
      <Flex flexDirection="row" style={{ width: '350px' }}>
        <Flex flexGrow={1}>
          <Typography variant="h4">
            <Trans>Profiles</Trans>
          </Typography>
        </Flex>
        <Flex alignSelf="end">
          <IconButton onClick={navAdd}>
            <Add />
          </IconButton>
        </Flex>
      </Flex>
      <Routes>
        <Route
          element={<LayoutDashboardSub sidebar={<IdentitiesPanel />} outlet />}
        >
          <Route path=":walletId" element={<ProfileView />} />
          <Route path="add" element={<ProfileAdd />} />
        </Route>
      </Routes>
    </div>
  );
}
