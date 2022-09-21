import React from 'react';
import styled from 'styled-components';
import { Box } from '@mui/material';

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
const ipcRenderer = (window as any).ipcRenderer;

type ProgressBarType = {
  nftIdUrl: string;
  setValidateNFT: any;
  fetchBinaryContentDone: (valid: boolean) => void;
};

export default function NFTProgressBar({
  nftIdUrl,
  setValidateNFT,
  fetchBinaryContentDone,
}: ProgressBarType) {
  const [progressBarWidth, setProgressBarWidth] = React.useState(-1);

  React.useEffect(() => {
    let oldProgress = 0;
    ipcRenderer.on('fetchBinaryContentProgress', (_event, obj: any) => {
      if (obj.nftIdUrl === nftIdUrl) {
        const newProgress = Math.round(obj.progress * 100);
        if (newProgress !== oldProgress) {
          setProgressBarWidth(newProgress);
          oldProgress = newProgress;
        }
      }
    });
    ipcRenderer.on('fetchBinaryContentDone', (_event, obj: any) => {
      if (obj.nftIdUrl === nftIdUrl) {
        fetchBinaryContentDone(obj.valid);

        setProgressBarWidth(-1);
        setValidateNFT(false);
      }
    });
  }, []);

  if (progressBarWidth === -1) {
    return null;
  }

  return (
    <ProgressBar>
      <Box sx={{ width: `${progressBarWidth}%` }} />
    </ProgressBar>
  );
}
