import React from 'react';
import { Routes, Route } from 'react-router-dom';
import WalletDIDSelect from './WalletDIDSelect';
import WalletDIDCreate from './WalletDIDCreate';
import WalletDIDRecovery from './WalletDIDRecovery';

export default function WalletDIDList() {
  return (
    <Routes>
      <Route element={<WalletDIDSelect />} index />
      <Route element={<WalletDIDCreate />} path="create" />
      <Route element={<WalletDIDRecovery />} path="recovery" />
    </Routes>
  );
}
