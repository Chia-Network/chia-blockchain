import React from 'react';
import { Trans } from '@lingui/macro';
import { useGetPrivateKeyQuery } from '@chia/api-react';
import { Grid, Typography } from '@mui/material';
import styled from 'styled-components';
import AlertDialog from '../../components/AlertDialog';
import Loading from '../../components/Loading';

const StyledTypographyDD = styled(Typography)`
  word-break: break-all;
`;

type Props = {
  fingerprint: number;
};

export default function SelectKeyDetailDialog(props: Props) {
  const { fingerprint, ...rest } = props;

  const { data: privateKey, isLoading } = useGetPrivateKeyQuery({
    fingerprint,
  });

  if (isLoading) {
    return (
      <AlertDialog title={<Trans>Private key {fingerprint}</Trans>} {...rest}>
        <Loading center />
      </AlertDialog>
    );
  }

  return (
    <AlertDialog title={<Trans>Private key {fingerprint}</Trans>} {...rest}>
      <Grid
        container
        component="dl" // mount a Definition List
        spacing={2}
      >
        <Grid item>
          <Typography component="dt" variant="subtitle2">
            <Trans>Private key:</Trans>
          </Typography>
          <StyledTypographyDD component="dd" variant="body2">
            {privateKey.sk}
          </StyledTypographyDD>
        </Grid>
        <Grid item>
          <Typography component="dt" variant="subtitle2">
            <Trans>Public key: </Trans>
          </Typography>
          <StyledTypographyDD component="dd" variant="body2">
            {privateKey.pk}
          </StyledTypographyDD>
        </Grid>
        <Grid item>
          <Typography component="dt" variant="subtitle2">
            <Trans>Farmer public key: </Trans>
          </Typography>
          <StyledTypographyDD component="dd" variant="body2">
            {privateKey.farmerPk}
          </StyledTypographyDD>
        </Grid>
        <Grid item>
          <Typography component="dt" variant="subtitle2">
            <Trans>Pool public key: </Trans>
          </Typography>
          <StyledTypographyDD component="dd" variant="body2">
            {privateKey.poolPk}
          </StyledTypographyDD>
        </Grid>
        <Grid item>
          {privateKey.seed ? (
            <>
              <Typography component="dt" variant="subtitle2">
                <Trans>Seed: </Trans>
              </Typography>
              <StyledTypographyDD component="dd" variant="body2">
                {privateKey.seed}
              </StyledTypographyDD>
            </>
          ) : (
            <Typography component="dd" variant="body2">
              <Trans>No 24 word seed, since this key is imported.</Trans>
            </Typography>
          )}
        </Grid>
      </Grid>
    </AlertDialog>
  );
}
