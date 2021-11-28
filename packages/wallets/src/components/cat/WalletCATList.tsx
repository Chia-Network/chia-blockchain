import React from 'react';
import { Routes, Route } from 'react-router-dom';
import WalletCATSelect from './WalletCATSelect';
import WalletCATCreateNew from './WalletCATCreateNew';
import WalletCATCreateExistingSimple from './WalletCATCreateExistingSimple';

export default function WalletCATList() {
  return (
    <Routes>
      <Route element={<WalletCATSelect />} index />
      <Route path="create" element={<WalletCATCreateNew />} />
      <Route path="existing" element={<WalletCATCreateExistingSimple />} />
    </Routes>
  );
}
