import { useState } from 'react';
import { useGetOffersCountQuery, useGetAllOffersQuery } from '@chia/api-react';
import { OfferTradeRecord } from '@chia/api';

export default function useWalletOffers(
  defaultRowsPerPage = 5,
  defaultPage = 0,
  includeMyOffers = true,
  includeTakenOffers = true,
  sortKey?: 'CONFIRMED_AT_HEIGHT' | 'RELEVANCE',
  reverse?: boolean,
): {
  isLoading: boolean;
  offers?: OfferTradeRecord[];
  count?: number;
  error?: Error;
  page: number;
  rowsPerPage: number;
  pageChange: (rowsPerPage: number, page: number) => void;
} {
  const [rowsPerPage, setRowsPerPage] = useState<number>(defaultRowsPerPage);
  const [page, setPage] = useState<number>(defaultPage);

  const { data: counts, isLoading: isOffersCountLoading, error: offersCountError } = useGetOffersCountQuery();

  const all = rowsPerPage === -1;

  const start = all
    ? 0
    : page * rowsPerPage;

  let selectedCount = 0;

  if (includeMyOffers) {
    selectedCount += counts?.myOffersCount ?? 0;
  }

  if (includeTakenOffers) {
    selectedCount += counts?.takenOffersCount ?? 0;
  }

  const end = all
    ? selectedCount
    : start + rowsPerPage;

  const { data: offers, isLoading: isOffersLoading, error: offersError } = useGetAllOffersQuery({
    start,
    end,
    sortKey,
    reverse,
    includeMyOffers,
    includeTakenOffers,
  });

  const isLoading = isOffersLoading || isOffersCountLoading;
  const error = offersError || offersCountError;

  function handlePageChange(rowsPerPage: number, page: number) {
    setRowsPerPage(rowsPerPage);
    setPage(page);
  }

  return  {
    offers,
    count: selectedCount,
    page,
    rowsPerPage,
    isLoading,
    error,
    pageChange: handlePageChange,
  };
}
