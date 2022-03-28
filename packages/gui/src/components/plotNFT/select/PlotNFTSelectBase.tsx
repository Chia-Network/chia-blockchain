import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
// import { uniq } from 'lodash';
import styled from 'styled-components';
import { useWatch, useFormContext } from 'react-hook-form';
import {
  Button,
  Flex,
  Loading,
  CardStep,
  RadioGroup,
  Fee,
  TextField,
} from '@chia/core';
import {
  Alert,
  Grid,
  FormControl,
  FormControlLabel,
  Typography,
  Radio,
  Collapse,
} from '@mui/material';
import PoolInfo from '../../pool/PoolInfo';
import usePoolInfo from '../../../hooks/usePoolInfo';
// import usePlotNFTs from '../../../hooks/usePlotNFTs';

const StyledCollapse = styled(Collapse)`
  display: ${({ in: visible }) => (visible ? 'block' : 'none')};
`;

type Props = {
  step?: number;
  onCancel?: () => void;
  title: ReactNode;
  description?: ReactNode;
  hideFee?: boolean;
  feeDescription?: ReactNode;
};

export default function PlotNFTSelectBase(props: Props) {
  const { step, onCancel, title, description, hideFee, feeDescription } = props;
  // const { nfts } = usePlotNFTs();
  const { setValue } = useFormContext();
  const self = useWatch<boolean>({
    name: 'self',
  });

  const poolUrl = useWatch<string>({
    name: 'poolUrl',
  });

  const poolInfo = usePoolInfo(poolUrl);

  /*
  const groupsOptions = useMemo(() => {
    if (!nfts) {
      return [];
    }

    const urls = nfts
      .filter((nft) => !!nft.poolState.poolConfig.poolUrl)
      .map((nft) => nft.poolState.poolConfig.poolUrl);

    return uniq(urls);
  }, [nfts]);
  */

  function handleDisableSelfPooling() {
    if (self) {
      setValue('self', false);
    }
  }

  const showPoolInfo = !self && !!poolUrl;

  return (
    <>
      <CardStep
        step={step}
        title={
          <Flex gap={1} alignItems="center">
            <Flex flexGrow={1}>{title}</Flex>
            {onCancel && (
              <Button onClick={onCancel}>
                <Trans>Cancel</Trans>
              </Button>
            )}
          </Flex>
        }
      >
        {description && (
          <Typography variant="subtitle1">{description}</Typography>
        )}

        <Grid container spacing={4}>
          <Grid xs={12} item>
            <FormControl variant="filled" fullWidth>
              <RadioGroup name="self" boolean>
                <Flex gap={1} flexDirection="column">
                  <FormControlLabel
                    control={<Radio />}
                    label={
                      <Trans>
                        Self pool. When you win a block you will earn XCH
                        rewards.
                      </Trans>
                    }
                    value
                  />
                  <Flex gap={2}>
                    <FormControlLabel
                      value={false}
                      control={<Radio />}
                      label={<Trans>Connect to pool</Trans>}
                    />
                    <Flex
                      flexBasis={0}
                      flexGrow={1}
                      flexDirection="column"
                      gap={1}
                    >
                      <FormControl variant="filled" fullWidth>
                        <TextField
                          name="poolUrl"
                          label="Pool URL"
                          variant="filled"
                          autoComplete="on"
                          onClick={handleDisableSelfPooling}
                          onChange={handleDisableSelfPooling}
                          fullWidth
                        />
                      </FormControl>
                    </Flex>
                  </Flex>
                </Flex>
              </RadioGroup>
            </FormControl>
          </Grid>
          {!hideFee && (
            <Grid xs={12} lg={6} item>
              <Fee
                name="fee"
                type="text"
                variant="filled"
                label={<Trans>Fee</Trans>}
                fullWidth
              />
              {feeDescription}
            </Grid>
          )}
        </Grid>
      </CardStep>

      <StyledCollapse in={showPoolInfo}>
        <CardStep step={step + 1} title={<Trans>Verify Pool Details</Trans>}>
          {poolInfo.error && (
            <Alert severity="warning">{poolInfo.error.message}</Alert>
          )}

          {poolInfo.loading && <Loading center />}

          {poolInfo.poolInfo && <PoolInfo poolInfo={poolInfo.poolInfo} />}
        </CardStep>
      </StyledCollapse>
    </>
  );
}

PlotNFTSelectBase.defaultProps = {
  step: 1,
  onCancel: undefined,
  description: undefined,
  hideFee: false,
};
