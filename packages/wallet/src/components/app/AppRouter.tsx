import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { SelectKey, LayoutHero, LayoutMain } from '@chia/core';
import { WalletAdd, WalletImport, Wallets  } from '@chia/wallets';
import App from './App';

export default function AppRouter() {
  return (
    <Routes>
    <Route path="/" element={<App />}>
      <Route element={<LayoutHero />}>
        <Route index element={<SelectKey />} />
      </Route>
      <Route element={<LayoutHero back />}>
        <Route path="wallet/add" element={<WalletAdd />} />
        <Route path="wallet/import" element={<WalletImport />} />
      </Route>
      <Route element={<LayoutMain />}>
        <Route path="dashboard/wallets/:walletId?" element={<Wallets />} />
      </Route>
    </Route>
    <Route path="*" element={<Navigate to="/" />} />
  </Routes>
  );
}
