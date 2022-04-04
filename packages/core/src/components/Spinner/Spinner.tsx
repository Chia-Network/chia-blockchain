import React from 'react';
import { Backdrop, CircularProgress } from '@mui/material';
import styled from 'styled-components';

const StyledBackdrop = styled(Backdrop)`
  z-index: 2000;
`;

type Props = {
  show: boolean;
};

export default function Spinner(props: Props) {
  const { show } = props;

  return (
    <StyledBackdrop open={show}>
      <CircularProgress color="inherit" disableShrink />
    </StyledBackdrop>
  );
}
