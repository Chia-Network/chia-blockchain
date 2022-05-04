import React from 'react';
import { Routes, Route } from 'react-router-dom';
import NFTGallery from './gallery/NFTGallery';
import NFTDetail from './detail/NFTDetail';

/* ========================================================================== */

export default function NFTs() {
  return (
    <Routes>
      <Route index element={<NFTGallery />} />
      <Route path=":nftId" element={<NFTDetail />} />
    </Routes>
  );
}
