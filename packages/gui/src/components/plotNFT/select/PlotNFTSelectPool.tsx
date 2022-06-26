import React, {
  useState,
  ReactNode,
  forwardRef,
  useImperativeHandle,
} from 'react';
import { Alert } from '@mui/material';
import { t, Trans } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { ButtonLoading, Loading, Flex, Form, Back, chiaToMojo, ConfirmDialog, useOpenDialog } from '@chia/core';
import PlotNFTSelectBase from './PlotNFTSelectBase';
import normalizeUrl from '../../../util/normalizeUrl';
import getPoolInfo from '../../../util/getPoolInfo';
import InitialTargetState from '../../../types/InitialTargetState';
import useStandardWallet from '../../../hooks/useStandardWallet';
import PlotNFTSelectFaucet from './PlotNFTSelectFaucet';
import usePlotNFTs from '../../../hooks/usePlotNFTs';

export type SubmitData = {
  initialTargetState: InitialTargetState;
  fee?: string;
};

async function prepareSubmitData(data: FormData): SubmitData {
  const { self, fee, poolUrl } = data;
  const initialTargetState = {
    state: self ? 'SELF_POOLING' : 'FARMING_TO_POOL',
  };

  if (!self && poolUrl) {
    const normalizedPoolUrl = normalizeUrl(poolUrl);
    const { targetPuzzleHash, relativeLockHeight } = await getPoolInfo(
      normalizedPoolUrl,
    );
    if (!targetPuzzleHash) {
      throw new Error(t`Pool does not provide targetPuzzleHash.`);
    }
    if (relativeLockHeight === undefined) {
      throw new Error(t`Pool does not provide relativeLockHeight.`);
    }

    initialTargetState.poolUrl = normalizedPoolUrl;
    initialTargetState.targetPuzzleHash = targetPuzzleHash;
    initialTargetState.relativeLockHeight = relativeLockHeight;
  }

  const feeMojos = chiaToMojo(fee || '0');

  return {
    fee: feeMojos,
    initialTargetState,
  };
}

type FormData = {
  self: boolean;
  poolUrl?: string;
  fee?: string | number;
};

type Props = {
  step?: number;
  onCancel?: () => void;
  title: ReactNode;
  description?: ReactNode;
  submitTitle?: ReactNode;
  hideFee?: boolean;
  onSubmit: (data: SubmitData) => Promise<void>;
  defaultValues?: {
    fee?: string;
    self?: boolean;
    poolUrl?: string;
  };
  feeDescription?: ReactNode;
};

const PlotNFTSelectPool = forwardRef((props: Props, ref) => {
  const {
    step,
    onCancel,
    defaultValues,
    onSubmit,
    title,
    description,
    submitTitle,
    hideFee,
    feeDescription,
  } = props;
  const [loading, setLoading] = useState<boolean>(false);
  const { balance, loading: walletLoading } = useStandardWallet();
  const { nfts } = usePlotNFTs();
  const openDialog = useOpenDialog();
  const exceededNFTLimit = nfts?.length >= 50;
  const hasBalance = !!balance && balance > 0;

  const methods = useForm<FormData>({
    defaultValues: {
      fee: '',
      self: true,
      poolUrl: '',
      ...defaultValues,
    },
  });

  useImperativeHandle(ref, () => ({
    async getSubmitData() {
      const data = methods.getValues();

      return prepareSubmitData(data);
    },
  }));

  async function handleSubmit(data: FormData) {
    let createNFT = true;
    if (nfts?.length > 10) {
       createNFT = await openDialog(
        <ConfirmDialog
          title={<Trans>Too Many Plot NFTs</Trans>}
          confirmColor="danger"
        >
          <Trans>
            You already have more than 10 Plot NFTs. Click OK if you're sure you want to create a new one.
          </Trans>
        </ConfirmDialog>
      );
    }
    if (createNFT && !exceededNFTLimit) {
    try {
      setLoading(true);

      const submitData = await prepareSubmitData(data);

      await onSubmit(submitData);
    } finally {
      setLoading(false);
    }
    }
  }

  if (walletLoading) {
    return <Loading />;
  }

  if (!hasBalance) {
    return (
      <Flex flexDirection="column" gap={3}>
        {!onCancel && (
          <Form methods={methods} onSubmit={handleSubmit}>
            <Back variant="h5" form>
              <Trans>Join a Pool</Trans>
            </Back>
          </Form>
        )}
        <PlotNFTSelectFaucet step={step} onCancel={onCancel} />
      </Flex>
    );
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex flexDirection="column" gap={3}>
        {!onCancel && (
          <Back variant="h5" form>
            <Trans>Join a Pool</Trans>
          </Back>
        )}

        <PlotNFTSelectBase
          step={step}
          onCancel={onCancel}
          title={title}
          description={description}
          hideFee={hideFee}
          feeDescription={feeDescription}
        />
        {exceededNFTLimit && <Alert severity="error">
          <Trans>You already have 50 or more Plot NFTs.</Trans>
        </Alert>}
        {!onCancel && (
          <Flex gap={1} justifyContent="right">
            <ButtonLoading
              loading={loading}
              disabled={exceededNFTLimit}
              color="primary"
              type="submit"
              variant="contained"
            >
              {submitTitle}
            </ButtonLoading>
          </Flex>
        )}
      </Flex>
    </Form>
  );
});

PlotNFTSelectPool.defaultProps = {
  step: undefined,
  onCancel: undefined,
  defaultValues: undefined,
  title: undefined,
  description: undefined,
  hideFee: false,
  submitTitle: <Trans>Create</Trans>,
};

export default PlotNFTSelectPool;
