import React from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { SelectKey, LayoutHero, LayoutMain, LayoutDashboard, Mode, useMode } from '@chia/core';
import { WalletAdd, WalletImport, Wallets } from '@chia/wallets';
import AppProviders from './AppProviders';
import FullNode from '../fullNode/FullNode';
import Block from '../block/Block';
import Settings from '../settings/Settings';
import Plot from '../plot/Plot';
import Farm from '../farm/Farm';
import Pool from '../pool/Pool';
import DashboardSideBar from '../dashboard/DashboardSideBar';
import SettingsPanel from '../settings/SettingsPanel';

export default function AppRouter() {
  const [mode] = useMode();

  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<AppProviders outlet />}>
          <Route element={<LayoutHero settings={<SettingsPanel />} outlet />}>
            <Route index element={<SelectKey />} />
          </Route>
          <Route element={<LayoutHero settings={<SettingsPanel />} back outlet />}>
            <Route path="wallet/add" element={<WalletAdd />} />
            <Route path="wallet/import" element={<WalletImport />} />
          </Route>
          {mode === Mode.WALLET ? (
            <Route element={<LayoutDashboard settings={<SettingsPanel />} outlet />}>
              <Route path="dashboard" element={<Navigate to="wallets" />} />
              <Route path="dashboard/wallets/*" element={<Wallets />} />
              <Route path="dashboard/*" element={<Navigate to="wallets" />} />
            </Route>
          ) : (
            <Route element={<LayoutDashboard settings={<SettingsPanel />} sidebar={<DashboardSideBar />} outlet />}>
              <Route path="dashboard" element={<FullNode />} />
              <Route path="dashboard/block/:headerHash" element={<Block />} />
              <Route path="dashboard/wallets/*" element={<Wallets />} />
              <Route path="dashboard/settings/*" element={<Settings />} />
              <Route path="dashboard/plot/*" element={<Plot />} />
              <Route path="dashboard/farm/*" element={<Farm />} />
              <Route path="dashboard/pool/*" element={<Pool />} />
            </Route>
          )}
        </Route>
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </HashRouter>
  );
}
