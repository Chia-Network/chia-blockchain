import React, { ReactNode } from 'react';
import { Paper } from '@material-ui/core';
import styled from 'styled-components';
// @ts-ignore
import ScrollToBottom from 'react-scroll-to-bottom';

const StyledScrollToBottom = styled(ScrollToBottom)`
  width: 100%;
  height: 100%;
`;

const StyledPaper = styled(Paper)`
  background-color: #272c34;
  color: white;
  min-width: 50vw;
  width: 100%;
  height: 40vh;

  pre {
    word-break: break-all;
    white-space: pre-wrap;
    padding: ${({ theme }) => `${theme.spacing(1)}px ${theme.spacing(2)}px`};
  }
`;

type Props = {
  children?: ReactNode;
};

export default function Log(props: Props) {
  const { children } = props;

  return ( 
    <StyledPaper>
      <StyledScrollToBottom debug={false}>
        <pre>{children}</pre>
      </StyledScrollToBottom>
    </StyledPaper>
  );
}

Log.defaultProps = {
  children: undefined,
};
