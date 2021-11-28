import React from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { SelectKey, LayoutHero, LayoutDashboard } from '@chia/core';
import { WalletAdd, WalletImport, Wallets  } from '@chia/wallets';
import App from './App';
import FullNode from '../fullNode/FullNode';
import Block from '../block/Block';
import DashboardSideBar from '../dashboard/DashboardSideBar';

export default function AppRouter() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route element={<LayoutHero />}>
            <Route index element={<SelectKey />} />
          </Route>
          <Route element={<LayoutHero back />}>
            <Route path="wallet/add" element={<WalletAdd />} />
            <Route path="wallet/import" element={<WalletImport />} />
          </Route>
          <Route element={<LayoutDashboard sidebar={<DashboardSideBar />} />}>
            <Route path="dashboard/" element={<FullNode />} />
            <Route path="dashboard/block/:headerHash" element={<Block />} />
            <Route path="dashboard/wallets/*" element={<Wallets />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </HashRouter>
  );
}
