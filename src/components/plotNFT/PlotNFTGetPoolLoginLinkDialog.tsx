import React, { useEffect, useState } from 'react';
import { t, Trans } from '@lingui/macro';
import { Alert } from '@material-ui/lab';
import styled from 'styled-components';
import { CopyToClipboard, Flex, Link, Loading } from '@chia/core';
import {
  Button,
  Dialog,
  DialogActions,
  DialogTitle,
  DialogContent,
  Typography,
} from '@material-ui/core';
import { useDispatch } from 'react-redux';
import { getPoolLoginLink } from '../../modules/farmerMessages';
import PlotNFT from '../../types/PlotNFT';
import PlotNFTExternal from '../../types/PlotNFTExternal';

const StyledLoginLink = styled(Typography)`
  word-break: break-all;
`;

type Props = {
  open: boolean;
  onClose: () => void;
  nft: PlotNFT | PlotNFTExternal;
};

export default function PlotNFTGetPoolLoginLinkDialog(props: Props) {
  const { onClose, open, nft } = props;
  const dispatch = useDispatch();
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | undefined>(undefined);
  const [loginLink, setLoginLink] = useState<string | undefined>(undefined);

  const { pool_state: { pool_config: { pool_url, launcher_id } } } = nft;

  function handleClose() {
    onClose();
  }

  async function updatePoolLoginLink() {
    setError(undefined);
    setLoginLink(undefined);

    if (!pool_url) {
      setLoading(false);
      setError(new Error(t`This plot NFT is not connected to pool`));
      return;
    }

    try {
      setLoading(true);
      const response = await dispatch(getPoolLoginLink(launcher_id));
      if (response.success !== true) {
        throw new Error(response.message ?? t`Something went wrong`);
      }
      setLoginLink(response?.login_link);
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    updatePoolLoginLink();
  }, [pool_url]); // eslint-disable-line

  return (
    <Dialog
      disableBackdropClick
      disableEscapeKeyDown
      maxWidth="md"
      open={open}
    >
      <DialogTitle>
        <Trans>Pool Login Link</Trans>
      </DialogTitle>
      <DialogContent dividers>
        <Flex gap={2} flexDirection="column">
          {loading ? (
            <Flex justifyContent="center">
              <Loading />
            </Flex>
          ) : (
            <Flex flexDirection="column" gap={2}>
              {error && <Alert severity="error">{error.message}</Alert>}

              <StyledLoginLink variant="body2">
                {loginLink}
              </StyledLoginLink>

              <Typography variant="body2" color="textSecondary">
                <Trans>
                  It is a one-time login link that can be used to log in to a pool's website.
                  It contains a signature using the farmer's key from the plot NFT.
                  Not all pools support this feature.
                </Trans>
                {' '}
                <Link
                  target="_blank"
                  href="https://github.com/Chia-Network/pool-reference/blob/main/SPECIFICATION.md#get-login"
                  noWrap
                >
                  <Trans>Learn More</Trans>
                </Link>
              </Typography>
            </Flex>
          )}
        </Flex>
      </DialogContent>
      <DialogActions>
        {loginLink && (
          <CopyToClipboard value={loginLink} size="medium" />
        )}
        
        <Button onClick={handleClose} color="secondary">
          <Trans>OK</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}

PlotNFTGetPoolLoginLinkDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
