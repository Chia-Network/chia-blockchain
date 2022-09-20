import React from 'react';
import { useFormContext } from 'react-hook-form';
import { Trans } from '@lingui/macro';
import { Wallet } from '@chia/api';
// import { useGetWalletBalanceQuery } from '@chia/api-react';
import { Amount, Flex } from '@chia/core';
import { Farming } from '@chia/icons';
import { Typography } from '@mui/material';
import OfferBuilderSection, {
  OfferBuilderSectionProps,
} from './OfferBuilderSection';
import useOfferBuilderContext from './useOfferBuilderContext';
import OfferBuilderSectionType from './OfferBuilderSectionType';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';
import { isOpposingSectionExpanded } from './utils';

type Props = {
  wallet?: Wallet;
  formNamePrefix: string;
};

type ReadOnlyProps = Props;

function ReadOnly(props: ReadOnlyProps): JSX.Element {
  const { formNamePrefix } = props;
  const { watch } = useFormContext();
  const amount = watch(`${formNamePrefix}.amount`);

  return (
    <Flex flexDirection="column" gap={1}>
      <Typography variant="body2">
        <Trans>Amount</Trans>
      </Typography>
      <Typography variant="subtitle1">{amount}</Typography>
      <Typography variant="caption">Balance: 40,000,000 XCH</Typography>
    </Flex>
  );
}

type EditableProps = Props;

function Editable(props: EditableProps): JSX.Element {
  const { formNamePrefix } = props;
  // const { data: walletBalance, isLoading: isLoadingWalletBalance } =
  //   useGetWalletBalanceQuery(
  //     {
  //       walletId: tokenWalletInfo.walletId,
  //     }
  //   );

  return (
    <Flex flexDirection="column" gap={1}>
      <Amount
        variant="filled"
        color="secondary"
        label={<Trans>Amount</Trans>}
        id={`${formNamePrefix}.amount`}
        name={`${formNamePrefix}.amount`}
        required
        fullWidth
      />
      <Typography variant="caption">Balance: 40,000,000 XCH</Typography>
    </Flex>
  );
}

type OfferBuilderXCHSectionProps = Props &
  OfferBuilderSectionProps & {
    side: OfferBuilderTradeSide;
    editable?: boolean;
  };

export default function OfferBuilderXCHSection(
  props: OfferBuilderXCHSectionProps,
): JSX.Element {
  const { side, editable = false, ...rest } = props;
  const { expandedSections } = useOfferBuilderContext();
  const canToggleExpansion = !isOpposingSectionExpanded(
    side,
    OfferBuilderSectionType.XCH,
    expandedSections,
  );
  const content = editable ? <Editable {...rest} /> : <ReadOnly {...rest} />;

  return (
    <OfferBuilderSection
      icon={<Farming />}
      title={<Trans>XCH</Trans>}
      subtitle={
        <Trans>
          Chia (XCH) is a digital currency that is secure and sustainable
        </Trans>
      }
      side={side}
      sectionType={OfferBuilderSectionType.XCH}
      canToggleExpansion={canToggleExpansion}
    >
      {content}
    </OfferBuilderSection>
  );
}
