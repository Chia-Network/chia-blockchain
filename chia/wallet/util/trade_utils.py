from typing import Dict

from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.trade_status import TradeStatus


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
    """Convenience function to return only part of trade record we care about and show correct status to the ui"""
    result = {}
    result["trade_id"] = record.trade_id.hex()
    result["sent"] = record.sent
    result["is_my_offer"] = record.is_my_offer
    result["created_at_time"] = record.created_at_time
    result["accepted_at_time"] = record.accepted_at_time
    result["confirmed_at_index"] = record.confirmed_at_index
    result["status"] = trade_status_ui_string(TradeStatus(record.status))
    result["offer_dict"] = record.offer.arbitrage()
    return result


# Returns the relative difference in value between the amount outputted by a puzzle and solution and a coin's amount
def get_output_discrepancy_for_puzzle_and_solution(coin, puzzle, solution):
    discrepancy = coin.amount - get_output_amount_for_puzzle_and_solution(puzzle, solution)
    return discrepancy

    # Returns the amount of value outputted by a puzzle and solution


def get_output_amount_for_puzzle_and_solution(puzzle: Program, solution: Program) -> int:
    error, conditions, cost = conditions_dict_for_solution(puzzle, solution, INFINITE_COST)
    total = 0
    if conditions:
        for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
            total += Program.to(_.vars[1]).as_int()
    return total
