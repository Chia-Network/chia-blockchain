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
  uri: string;
  setIsValid: any;
  setValidateNFT: any;
  setValidationProcessed: any;
};

export default function NFTProgressBar({
  uri,
  setIsValid,
  setValidateNFT,
  setValidationProcessed,
}: ProgressBarType) {
  const [progressBarWidth, setProgressBarWidth] = React.useState(-1);

  React.useEffect(() => {
    ipcRenderer.on('fetchBinaryContentProgress', (_event, obj: any) => {
      if (uri === obj.uri) {
        setProgressBarWidth(obj.progress);
      }
    });
    ipcRenderer.on('fetchBinaryContentDone', (_event, obj: any) => {
      setValidationProcessed(true);
      setIsValid(obj.valid);
      setProgressBarWidth(-1);
      setValidateNFT(false);
    });
  }, []);

  if (progressBarWidth === -1) {
    return null;
  }

  return (
    <ProgressBar>
      <Box sx={{ width: `${progressBarWidth * 100}%` }} />
    </ProgressBar>
  );
}
