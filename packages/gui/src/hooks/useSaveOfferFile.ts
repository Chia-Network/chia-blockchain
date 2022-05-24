import { OfferTradeRecord } from '@chia/api';
import { useGetOfferDataMutation } from '@chia/api-react';
import { useShowSaveDialog } from '@chia/core';
import fs from 'fs';
import { suggestedFilenameForOffer } from '../components/offers/utils';
import useAssetIdName from './useAssetIdName';

export type SaveOfferFileHook = (tradeId: string) => Promise<void>;

export default function useSaveOfferFile(): [SaveOfferFileHook] {
  const [getOfferData] = useGetOfferDataMutation();
  const { lookupByAssetId } = useAssetIdName();
  const showSaveDialog = useShowSaveDialog();

  async function saveOfferFile(tradeId: string): Promise<void> {
    const {
      data: response,
    }: {
      data: { offer: string; tradeRecord: OfferTradeRecord; success: boolean };
    } = await getOfferData(tradeId);
    const { offer: offerData, tradeRecord, success } = response;
    if (success === true) {
      const dialogOptions = {
        defaultPath: suggestedFilenameForOffer(
          tradeRecord.summary,
          lookupByAssetId,
        ),
      };
      const result = await showSaveDialog(dialogOptions);
      const { filePath, canceled } = result;

      if (!canceled && filePath) {
        try {
          fs.writeFileSync(filePath, offerData);
        } catch (err) {
          console.error(err);
        }
      }
    }
  }

  return [saveOfferFile];
}
