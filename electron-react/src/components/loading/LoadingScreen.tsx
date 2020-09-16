import React, { ReactNode } from 'react';
import { useTheme } from '@material-ui/core/styles';
import { CircularProgress } from '@material-ui/core';
import theme from "../../theme/default";

type Props = {
  children: ReactNode,
};

export default function LoadingScreen(props: Props) {
  const { children } = props;
  const theme = useTheme();

  return (
    <div style={theme.div}>
      <div style={theme.center}>
        <h3 style={theme.h3}>{children}</h3>
        <CircularProgress style={theme.h3} />
      </div>
    </div>
  );
}
