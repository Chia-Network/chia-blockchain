import React from "react";
import { ThemeProvider } from "@material-ui/core/styles";
import CssBaseline from "@material-ui/core/CssBaseline";

import RsgWrapper from "react-styleguidist/lib/client/rsg-components/Wrapper/Wrapper";

import muiTheme from "./muiTheme";
import "./assets/css/App.css";

const RsgMuiWrapper = ({ children, ...rest }) => (
  <>
    <CssBaseline />
    <RsgWrapper {...rest}>
      <ThemeProvider theme={muiTheme}>{children}</ThemeProvider>
    </RsgWrapper>
  </>
);

export default RsgMuiWrapper;
