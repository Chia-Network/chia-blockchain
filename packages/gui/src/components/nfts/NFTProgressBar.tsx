import React from 'react';
import styled from 'styled-components';

const ProgressBar = styled.div`
  width: 100%;
  height: 12px;
  border: 1px solid #abb0b2;
  border-radius: 3px;
  margin-top: 30px !important;
  margin-left: 0 !important;
  > div {
    background: #b0debd;
    height: 10px;
    border-radius: 2px;
  }
`;

export default function NFTProgressBar({ percentage }) {
  if (percentage === -1) return null;
  return (
    <ProgressBar>
      <div style={{ width: `${percentage * 100}%` }}></div>
    </ProgressBar>
  );
}
