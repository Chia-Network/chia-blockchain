import React from "react";
import { connect, useSelector, useDispatch } from "react-redux";

import { makeStyles, withStyles } from "@material-ui/core/styles";
import Typography from "@material-ui/core/Typography";
import Link from "@material-ui/core/Link";
import IconButton from "@material-ui/core/IconButton";
import Container from "@material-ui/core/Container";

import InfoIcon from "../../assets/img/info_icon.svg";
import InfoIconDark from "../../assets/img/info_icon_dark.svg";
import Table from "../../components/table";
import Tooltip from "../../components/tooltip";

import {
  useFarmedChiaInfo,
  usePlotsInfo,
  useTotalNetworkSpace,
  useExpectedTimeToWin,
  useLatestBlockChallenges,
} from "../../hooks/farm";
import { mojo_to_chia_string } from "../../util/chia";

import { clearSend } from "../../modules/message";

const styles = (theme) => {
  console.log(theme);

  return {
    sectionHeader: {
      fontWeight: 500,
      fontSize: "28px",
      lineHeight: "33px",
      letterSpacing: "0.575px",
      color: "#111111",
    },
    sectionParagraph: {
      fontSize: "22px",
      lineHeight: "32px",
      letterSpacing: "0.55px",
      color: "#66666B",
    },
    container: {
      paddingTop: theme.spacing(3),
      paddingRight: theme.spacing(6),
      paddingLeft: theme.spacing(6),
      paddingBottom: theme.spacing(3),
    },
    spacer: {
      height: theme.spacing(5),
    },
  };
};

const useStyles = makeStyles(styles);

function Farm() {
  const classes = useStyles();

  const [totalChiaFarmed, lastHeightFarmed] = useFarmedChiaInfo();
  const [plots, totalPlotSize] = usePlotsInfo();
  const [
    totalNetworkSpace,
    formattedTotalNetworkSpace,
  ] = useTotalNetworkSpace();

  const [
    expectedHoursToWin,
    localPlotsToNetworkProportion,
  ] = useExpectedTimeToWin(totalPlotSize, totalNetworkSpace);

  const [latestChallenges] = useLatestBlockChallenges();

  return (
    <div className={classes.container}>
      <Typography className={classes.sectionHeader} variant="h5">
        Your Farm Overview{" "}
        <Tooltip
          arrow
          placement="right"
          interactive
          title={
            <div>
              A farm is a group of plots harvested by harvesters. The combined
              plot sizes create your farms chance of winning th next block.{" "}
              <Link href="https://github.com/Chia-Network/chia-blockchain/wiki/Network-Architecture">
                Learn more
              </Link>
            </div>
          }
        >
          <img src={InfoIconDark} alt="Info" />
        </Tooltip>
      </Typography>

      <div className={classes.spacer}></div>

      <Typography className={classes.sectionParagraph} variant="body1">
        Farmers earn block rewards and transaction fees by committing spare
        space to the network to help secure transactions.{" "}
        <Link href="https://github.com/Chia-Network/chia-blockchain/wiki/Network-Architecture">
          Learn more
        </Link>
      </Typography>

      <div className={classes.spacer}></div>

      {/* TODO Farmer Status */}
      <Table
        header={[
          "Total Chia Farmed",
          "XCH Farming Rewards",
          "XCH Fees Collected",
          "Last Height Farmed",
        ]}
        data={[
          mojo_to_chia_string(totalChiaFarmed), // TODO
          "???", // TODO
          "???", // TODO
          lastHeightFarmed,
        ]}
      ></Table>

      <div className={classes.spacer}></div>

      <Table
        header={[
          "Plot Count",
          "Total Size of Plots",
          "Total Network Space",
          <div style={{ fontSize: "22px", display: "flex" }}>
            <div style={{ marginRight: "2px" }}>Expected Time to Win</div>
            <Tooltip
              arrow
              placement="top"
              interactive
              title={`You have ${(localPlotsToNetworkProportion * 100).toFixed(
                6
              )}% of the total network space. Farming a block will take an expected ${expectedHoursToWin.toFixed(
                3
              )} hours.`}
            >
              <img src={InfoIcon} alt="Info" />
            </Tooltip>
          </div>,
        ]}
        data={[
          plots.length,
          `${Math.floor(totalPlotSize / Math.pow(1024, 3)).toString(10)} GiB`,
          {
            content: formattedTotalNetworkSpace,
            annotation: "Best estimate over last 1 hour",
          },
          `${expectedHoursToWin.toFixed(1)} hours`,
        ]}
      ></Table>

      <div className={classes.spacer}></div>
      <div className={classes.spacer}></div>

      <Typography className={classes.sectionHeader} variant="h5">
        Latest Block Challenges
      </Typography>

      <div className={classes.spacer}></div>

      <Typography className={classes.sectionParagraph} variant="body1">
        Below are the current block challenges. You may or may not have a proof
        of space for these challenges. These blocks do not currently contain a
        proof of time.
      </Typography>

      <div className={classes.spacer}></div>

      <Table
        header={[
          "Challenge Hash",
          "Height",
          "Number of Proofs",
          <div style={{ fontSize: "22px", display: "flex" }}>
            <div style={{ marginRight: "2px" }}>Best Estimate</div>
            <Tooltip
              arrow
              placement="top"
              interactive
              title="Best Estimate is how many seconds of time must be proved for your proofs."
            >
              <img src={InfoIcon} alt="Info" />
            </Tooltip>
          </div>,
        ]}
        data={latestChallenges.map((challenge) => [
          challenge.challenge,
          challenge.height,
          challenge.estimates.length,
          challenge.estimates.length > 0
            ? Math.floor(
                Math.min.apply(Math, challenge.estimates) / 60
              ).toString() + " minutes"
            : "",
        ])}
      />

      <div className={classes.spacer}></div>

      <Typography className={classes.sectionParagraph} variant="body1">
        *Want to explore Chia’s blocks further? Check out{" "}
        <Link href="https://www.chiaexplorer.com/">Chia Explorer</Link> built by
        an open source developer.
      </Typography>

      <div className={classes.spacer}></div>
      <div className={classes.spacer}></div>

      <Typography className={classes.sectionHeader} variant="h5">
        Latest Attempted Proof{" "}
        <Tooltip
          arrow
          placement="right"
          interactive
          title="This table shows you the last time your farm attempted to win a
                block challenge."
        >
          <img src={InfoIcon} alt="Info" />
        </Tooltip>
      </Typography>

      <div className={classes.spacer}></div>

      <Table
        header={["Height", "Date", "Time"]}
        data={[
          [2029, "January -5-2019", "44:25:54"],
          [2029, "January -5-2019", "44:25:54"],
          [2029, "January -5-2019", "44:25:54"],
        ]}
      />

      <div className={classes.spacer}></div>
      <div className={classes.spacer}></div>

      {/* TODO Advanced Options */}
    </div>
  );
}

const mapStateToProps = (state, ownProps) => {
  return {
    wallets: state.wallet_state.wallets,
  };
};

const mapDispatchToProps = (dispatch, ownProps) => {
  return {
    clearSend: () => {
      dispatch(clearSend());
    },
  };
};
export default connect(mapStateToProps, mapDispatchToProps)(Farm);
