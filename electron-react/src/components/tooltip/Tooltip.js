import React from "react";
import PropTypes from "prop-types";
import MuiTooltip from "@material-ui/core/Tooltip";
import { withStyles } from "@material-ui/core/styles";

const Tooltip = withStyles({
  tooltip: {
    color: "#111111",
    background: "#EEEEEE",
    boxShadow: "0px 1px 4px rgba(0, 0, 0, 0.2)",

    fontWeight: 300,
    fontSize: "11px",
    lineHeight: "13px",
    letterSpacing: "0.575px",

    padding: "13px 30px 13px 21px",
  },
  arrow: {
    color: "#EEEEEE",
  },
})(MuiTooltip);

export default Tooltip;
