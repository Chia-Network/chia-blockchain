import React from 'react';
import { LayoutDashboardSub } from '@chia/core';
import { Navigate } from 'react-router-dom'
import WalletCreate from './create/WalletCreate';
import { Routes, Route } from 'react-router-dom';
import WalletsSidebar from './WalletsSidebar';
import Wallet from './Wallet';

export default function Wallets() {
  return (
    <Routes>
      <Route element={<LayoutDashboardSub outlet />}>
        <Route path="create/*" element={<WalletCreate />} />
      </Route>
      <Route element={<LayoutDashboardSub sidebar={<WalletsSidebar />} outlet />}>
        <Route path=":walletId" element={<Wallet />} />
        <Route path="*" element={<Navigate to="1" />} />
      </Route>
    </Routes>
  );
}
