import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import type { NFT } from '@chia/api';
import {
  DropdownActions,
  type DropdownActionsChildProps,
  Flex,
  useOpenDialog,
} from '@chia/core';
import { Offers as OffersIcon } from '@chia/icons';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  ListItemIcon,
  MenuItem,
  Typography,
} from '@mui/material';
import { ArrowForward as TransferIcon } from '@mui/icons-material';
import NFTCreateOfferDemoDialog from './NFTCreateOfferDemo';
import NFTTransferDemo from './NFTTransferDemo';
import NFTSelection from '../../types/NFTSelection';

/* ========================================================================== */
/*                          Common Action Types/Enums                         */
/* ========================================================================== */

enum NFTContextualActionTypes {
  CreateOffer = 1 << 0, // 1
  Transfer = 1 << 1, // 2
}

type NFTContextualActionProps = {
  onClose: () => void;
  selection?: NFTSelection;
};

/* ========================================================================== */
/*                             Create Offer Action                            */
/* ========================================================================== */

type NFTCreateOfferContextualActionProps = NFTContextualActionProps;

function NFTCreateOfferContextualAction(
  props: NFTCreateOfferContextualActionProps,
) {
  const { onClose, selection } = props;
  const openDialog = useOpenDialog();
  const selectedNft: NFT | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleCreateOffer() {
    if (!selectedNft) {
      throw new Error('No NFT selected');
    }

    openDialog(
      <NFTCreateOfferDemoDialog
        nft={selectedNft}
        referrerPath={location.hash.split('#').slice(-1)[0]}
      />,
    );
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleCreateOffer();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <OffersIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Create Offer</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                             Transfer NFT Action                            */
/* ========================================================================== */

type NFTTransferContextualActionProps = NFTContextualActionProps;

function NFTTransferContextualAction(props: NFTTransferContextualActionProps) {
  const { onClose, selection } = props;
  const openDialog = useOpenDialog();
  const selectedNft: NFT | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

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
            <NFTTransferDemo nft={selectedNft} />
          </Flex>
        </DialogContent>
      </Dialog>,
    );
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleTransferNFT();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <TransferIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Transfer NFT</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                             Contextual Actions                             */
/* ========================================================================== */

type NFTContextualActionsProps = {
  selection?: NFTSelection;
  availableActions: NFTContextualActionTypes;
};

export default function NFTContextualActions(props: NFTContextualActionsProps) {
  const { selection, availableActions } = props;

  const actions = useMemo(() => {
    const actionComponents = {
      [NFTContextualActionTypes.CreateOffer]: NFTCreateOfferContextualAction,
      [NFTContextualActionTypes.Transfer]: NFTTransferContextualAction,
    };

    return Object.keys(NFTContextualActionTypes)
      .map(Number)
      .filter(Number.isInteger)
      .filter((key) => actionComponents.hasOwnProperty(key))
      .filter((key) => availableActions & key)
      .map((key) => actionComponents[key]);
  }, [availableActions]);

  return (
    <DropdownActions label={<Trans>Actions</Trans>} variant="outlined">
      {({ onClose }: DropdownActionsChildProps) => (
        <>
          {actions.map((Action) => (
            <Action onClose={onClose} selection={selection} />
          ))}
        </>
      )}
    </DropdownActions>
  );
}

NFTContextualActions.defaultProps = {
  selection: undefined,
  availableActions:
    NFTContextualActionTypes.CreateOffer | NFTContextualActionTypes.Transfer,
};
