import React, { useMemo, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { Alert } from '@material-ui/lab';
import { uniq } from 'lodash';
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
  Grid,
  FormControl,
  FormControlLabel,
  Typography,
  Radio,
  Collapse,
} from '@material-ui/core';
import PoolInfo from '../../pool/PoolInfo';
import usePoolInfo from '../../../hooks/usePoolInfo';
import usePlotNFTs from '../../../hooks/usePlotNFTs';

const StyledCollapse = styled(Collapse)`
  display: ${({ in: visible }) => (visible ? 'block' : 'none')};
`;

type Props = {
  step?: number;
  onCancel?: () => void;
  title: ReactNode;
  description?: ReactNode;
  hideFee?: boolean;
};

export default function PlotNFTSelectBase(props: Props) {
  const { step, onCancel, title, description, hideFee } = props;
  const { nfts } = usePlotNFTs();
  const { control, setValue } = useFormContext();
  const self = useWatch<boolean>({
    control,
    name: 'self',
  });

  const poolUrl = useWatch<string>({
    control,
    name: 'poolUrl',
  });

  const poolInfo = usePoolInfo(poolUrl);

  /*
  const groupsOptions = useMemo(() => {
    if (!nfts) {
      return [];
    }

    const urls = nfts
      .filter((nft) => !!nft.pool_state.pool_config.pool_url)
      .map((nft) => nft.pool_state.pool_config.pool_url);

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
                          autoComplete="pool-url"
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
            </Grid>
          )}
        </Grid>
      </CardStep>

      <StyledCollapse in={showPoolInfo}>
        <CardStep step={step + 1} title={<Trans>Verify Pool Details</Trans>}>
          {poolInfo.error && (
            <Alert severity="warning">{poolInfo.error.message}</Alert>
          )}

          {poolInfo.loading && (
            <Flex alignItems="center">
              <Loading />
            </Flex>
          )}

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
