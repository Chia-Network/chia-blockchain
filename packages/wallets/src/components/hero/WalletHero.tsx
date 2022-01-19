import React from 'react';
import { Routes, Route } from 'react-router-dom';
import WalletHeroWallets from './WalletHeroWallets';
import WalletHeroAdd from './WalletHeroAdd';

export default function Wallets() {
  return (
    <Routes>
      <Route path="wallets" element={<WalletHeroWallets />} />
      <Route path="wallets/add" element={<WalletHeroAdd />} />
    </Routes>
  );
}
