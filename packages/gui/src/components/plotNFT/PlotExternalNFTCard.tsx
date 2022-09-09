import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router';
import {
  TooltipTypography,
  Flex,
  CardKeyValue,
  Tooltip,
  MenuItem,
  More,
  Loading,
  FormatLargeNumber,
  Link,
  useOpenDialog,
} from '@chia/core';
import {
  Box,
  Card,
  CardContent,
  Typography,
  ListItemIcon,
} from '@mui/material';
import { Plot as PlotIcon } from '@chia/icons';
import {
  /* Link as LinkIcon, */ Payment as PaymentIcon,
} from '@mui/icons-material';
import PlotNFTName from './PlotNFTName';
import PlotNFTExternalState from './PlotNFTExternalState';
import usePlotNFTExternalDetails from '../../hooks/usePlotNFTExternalDetails';
import PlotNFTExternal from '../../types/PlotNFTExternal';
import PlotNFTGraph from './PlotNFTGraph';
// import PlotNFTGetPoolLoginLinkDialog from './PlotNFTGetPoolLoginLinkDialog';
import PlotNFTPayoutInstructionsDialog from './PlotNFTPayoutInstructionsDialog';
import getPercentPointsSuccessfull from '../../util/getPercentPointsSuccessfull';

const StyledCard = styled(Card)`
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: visible;
  filter: grayscale(100%);
`;

const StyledCardContent = styled(CardContent)`
  display: flex;
  flex-direction: column;
  flex-grow: 1;
`;

const StyledSyncingFooter = styled(CardContent)`
  background-color: ${({ theme }) =>
    theme.palette.mode === 'dark' ? '#515151' : '#F6F6F6'};
  padding: 2rem 3rem;
  text-align: center;
  borer-top: 1px solid #d8d6d6;
`;

const StyledInvisibleContainer = styled(Box)`
  height: 0;
`;

export type PlotExternalNFTCardProps = {
  nft: PlotNFTExternal;
};

export default function PlotExternalNFTCard(props: PlotExternalNFTCardProps) {
  const {
    nft,
    nft: {
      poolState: {
        p2SingletonPuzzleHash,
        poolConfig: { launcherId, poolUrl },
        pointsFound24H,
        pointsAcknowledged24H,
      },
    },
  } = props;

  const percentPointsSuccessful24 = getPercentPointsSuccessfull(
    pointsAcknowledged24H,
    pointsFound24H,
  );

  const navigate = useNavigate();
  const openDialog = useOpenDialog();
  const { plots, isSelfPooling } = usePlotNFTExternalDetails(nft);
  const totalPointsFound24 = pointsFound24H.reduce(
    (accumulator, item) => accumulator + item[1],
    0,
  );

  function handleAddPlot() {
    navigate('/dashboard/plot/add', {
      state: {
        p2SingletonPuzzleHash,
      },
    });
  }

  /*
  function handleGetPoolLoginLink() {
    openDialog(<PlotNFTGetPoolLoginLinkDialog nft={nft} />);
  }
  */

  function handlePayoutInstructions() {
    openDialog(<PlotNFTPayoutInstructionsDialog nft={nft} />);
  }

  const rows = [
    {
      key: 'status',
      label: <Trans>Status</Trans>,
      value: <PlotNFTExternalState nft={nft} />,
    },
    {
      key: 'plotsCount',
      label: <Trans>Number of Plots</Trans>,
      value: plots ? (
        <FormatLargeNumber value={plots.length} />
      ) : (
        <Loading size="small" />
      ),
    },
    !isSelfPooling && {
      key: 'currentDifficulty',
      label: (
        <TooltipTypography
          title={
            <Trans>
              This difficulty is an artifically lower difficulty than on the
              real network, and is used when farming, in order to find more
              proofs and send them to the pool. The more plots you have, the
              higher difficulty you will have. However, the difficulty does not
              affect rewards.
            </Trans>
          }
        >
          <Trans>Current Difficulty</Trans>
        </TooltipTypography>
      ),
      value: <FormatLargeNumber value={nft.poolState.currentDifficulty} />,
    },
    !isSelfPooling && {
      key: 'currentPoints',
      label: (
        <TooltipTypography
          title={
            <Trans>
              This is the total number of points this plotNFT has with this
              pool, since the last payout. The pool will reset the points after
              making a payout.
            </Trans>
          }
        >
          <Trans>Current Points Balance</Trans>
        </TooltipTypography>
      ),
      value: <FormatLargeNumber value={nft.poolState.currentPoints} />,
    },
    !isSelfPooling && {
      key: 'pointsFoundSinceStart',
      label: (
        <TooltipTypography
          title={
            <Trans>
              This is the total number of points your farmer has found for this
              plot NFT. Each k32 plot will get around 10 points per day, so if
              you have 10TiB, should should expect around 1000 points per day,
              or 41 points per hour.
            </Trans>
          }
        >
          <Trans>Points Found Since Start</Trans>
        </TooltipTypography>
      ),
      value: <FormatLargeNumber value={nft.poolState.pointsFoundSinceStart} />,
    },
    !isSelfPooling && {
      key: 'pointsFound24',
      label: (
        <Typography>
          <Trans>Points Found in Last 24 Hours</Trans>
        </Typography>
      ),
      value: <FormatLargeNumber value={totalPointsFound24} />,
    },
    !isSelfPooling && {
      key: 'pointsFound24',
      label: (
        <Typography>
          <Trans>Points Successful in Last 24 Hours</Trans>
        </Typography>
      ),
      value: (
        <>
          <FormatLargeNumber
            value={Number(percentPointsSuccessful24 * 100).toFixed(2)}
          />
          {' %'}
        </>
      ),
    },
  ].filter((row) => !!row);

  return (
    <StyledCard>
      <StyledCardContent>
        <Flex flexDirection="column" gap={4.5} flexGrow={1}>
          <Flex flexDirection="column" gap={0}>
            <Flex gap={1}>
              <Box flexGrow={1}>
                <PlotNFTName nft={nft} variant="h6" />
              </Box>
              <More>
                <MenuItem onClick={handleAddPlot} close>
                  <ListItemIcon>
                    <PlotIcon />
                  </ListItemIcon>
                  <Typography variant="inherit" noWrap>
                    <Trans>Add a Plot</Trans>
                  </Typography>
                </MenuItem>
                {/*!isSelfPooling && (
                  <MenuItem
                    onClick={() => {
                      onClose();
                      handleGetPoolLoginLink();
                    }}
                  >
                    <ListItemIcon>
                      <LinkIcon />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      <Trans>View Pool Login Link</Trans>
                    </Typography>
                  </MenuItem>
                )*/}
                {!isSelfPooling && (
                  <MenuItem onClick={handlePayoutInstructions} close>
                    <ListItemIcon>
                      <PaymentIcon />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      <Trans>Edit Payout Instructions</Trans>
                    </Typography>
                  </MenuItem>
                )}
              </More>
            </Flex>
            <StyledInvisibleContainer>
              <Typography variant="body2" noWrap>
                {!!poolUrl && (
                  <Flex alignItems="center" gap={1}>
                    <Typography variant="body2" color="textSecondary">
                      <Trans>Pool:</Trans>
                    </Typography>
                    <Link target="_blank" href={poolUrl}>
                      {poolUrl}
                    </Link>
                  </Flex>
                )}
              </Typography>
            </StyledInvisibleContainer>
          </Flex>

          <Flex flexDirection="column" gap={2} flexGrow={1}>
            <Flex flexDirection="column" flexGrow={1}>
              <CardKeyValue rows={rows} hideDivider />
            </Flex>

            {!isSelfPooling && !!totalPointsFound24 && (
              <PlotNFTGraph points={pointsFound24H} />
            )}
          </Flex>

          <Flex flexDirection="column" gap={1}>
            <Typography variant="body1" color="textSecondary" noWrap>
              <Trans>Launcher Id</Trans>
            </Typography>
            <Tooltip title={launcherId} copyToClipboard>
              <Typography variant="body2" noWrap>
                {launcherId}
              </Typography>
            </Tooltip>
          </Flex>
        </Flex>
      </StyledCardContent>
      <StyledSyncingFooter>
        <Flex alignItems="center">
          <Typography variant="body2">
            <Trans>
              This plot NFT is assigned to a different key. You can still create
              plots for this plot NFT, but you can not make changes.
            </Trans>
          </Typography>
        </Flex>
      </StyledSyncingFooter>
    </StyledCard>
  );
}
