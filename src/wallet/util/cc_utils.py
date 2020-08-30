from typing import Tuple, Optional, Dict

from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.trade_record import TradeRecord
from src.wallet.trading.trade_status import TradeStatus


def trade_status_ui_string(status: TradeStatus):
    if status is TradeStatus.PENDING_CONFIRM:
        return "Pending Confirmation"
    elif status is TradeStatus.CANCELED:
        return "Canceled"
    elif status is TradeStatus.CONFIRMED:
        return "Confirmed"
    elif status is TradeStatus.PENDING_CANCEL:
        return "Pending Cancellation"
    elif status is TradeStatus.FAILED:
        return "Failed"
    elif status is TradeStatus.PENDING_ACCEPT:
        return "Pending"


def trade_record_to_dict(record: TradeRecord) -> Dict:
    """ Convinence function to return only part of trade record we care about and show correct status to the ui"""
    result = {}
    result["trade_id"] = record.trade_id.hex()
    result["sent"] = record.sent
    result["my_offer"] = record.my_offer
    result["created_at_time"] = record.created_at_time
    result["accepted_at_time"] = record.accepted_at_time
    result["confirmed_at_index"] = record.confirmed_at_index
    result["status"] = trade_status_ui_string(TradeStatus(record.status))
    success, offer_dict, error = get_discrepancies_for_spend_bundle(record.spend_bundle)
    if success is False or offer_dict is None:
        raise ValueError(error)
    result["offer_dict"] = offer_dict
    return result


def get_discrepancies_for_spend_bundle(
    trade_offer: SpendBundle,
) -> Tuple[bool, Optional[Dict], Optional[Exception]]:
    try:
        cc_discrepancies: Dict[bytes32, int] = dict()
        for coinsol in trade_offer.coin_solutions:
            puzzle = coinsol.solution.first()
            solution = coinsol.solution.rest().first()

            # work out the deficits between coin amount and expected output for each
            if cc_wallet_puzzles.check_is_cc_puzzle(puzzle):
                if not cc_wallet_puzzles.is_ephemeral_solution(solution):
                    colour = cc_wallet_puzzles.get_genesis_from_puzzle(puzzle).hex()
                    # get puzzle and solution
                    innerpuzzlereveal = cc_wallet_puzzles.get_inner_puzzle_from_puzzle(
                        puzzle
                    )
                    innersol = cc_wallet_puzzles.inner_puzzle_solution(solution)
                    # Get output amounts by running innerpuzzle and solution
                    out_amount = cc_wallet_puzzles.get_output_amount_for_puzzle_and_solution(
                        innerpuzzlereveal, innersol
                    )
                    # add discrepancy to dict of discrepancies
                    if colour in cc_discrepancies:
                        cc_discrepancies[colour] += coinsol.coin.amount - out_amount
                    else:
                        cc_discrepancies[colour] = coinsol.coin.amount - out_amount
            else:  # standard chia coin
                coin_amount = coinsol.coin.amount
                out_amount = cc_wallet_puzzles.get_output_amount_for_puzzle_and_solution(
                    puzzle, solution
                )
                diff = coin_amount - out_amount
                if "chia" in cc_discrepancies:
                    cc_discrepancies["chia"] = cc_discrepancies["chia"] + diff
                else:
                    cc_discrepancies["chia"] = diff

        return True, cc_discrepancies, None
    except Exception as e:
        return False, None, e
