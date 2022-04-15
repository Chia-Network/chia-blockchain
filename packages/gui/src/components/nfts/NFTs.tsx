import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, DropdownActions, useOpenDialog } from '@chia/core';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  ListItemIcon,
  MenuItem,
  Typography,
} from '@mui/material';
import { ArrowForward as TransferIcon } from '@mui/icons-material';
import NFTTransferDemo from './NFTTransferDemo';

export default function NFTs() {
  const openDialog = useOpenDialog();

  function handleTransferNFT() {
    const open = true;

    openDialog(
      <Dialog
        open={open}
        aria-labelledby="nft-transfer-dialog-title"
        aria-describedby="nft-transfer-dialog-description"
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle id="nft-transfer-dialog-title">
          <Typography variant="h6">
            <Trans>NFT Transfer Demo</Trans>
          </Typography>
        </DialogTitle>
        <DialogContent>
          <Flex justifyContent="center">
            <NFTTransferDemo />
          </Flex>
        </DialogContent>
      </Dialog>,
    );
  }

  return (
    <div>
      NFTs
      <Flex
        flexDirection="row"
        flexGrow={1}
        justifyContent="flex-end"
        gap={3}
        style={{ padding: '1rem' }}
      >
        <Flex gap={1} alignItems="center">
          <DropdownActions label={<Trans>Actions</Trans>}>
            {({ onClose }) => (
              <>
                <MenuItem
                  onClick={() => {
                    onClose();
                    handleTransferNFT();
                  }}
                >
                  <ListItemIcon>
                    <TransferIcon />
                  </ListItemIcon>
                  <Typography variant="inherit" noWrap>
                    <Trans>Transfer NFT</Trans>
                  </Typography>
                </MenuItem>
              </>
            )}
          </DropdownActions>
        </Flex>
      </Flex>
    </div>
  );
}
