import type CoinSolution from './CoinSolution';
import type G2Element from './G2Element';

type SpendBundle = {
  coin_solutions: CoinSolution[];
  aggregated_signature: G2Element;
};

export default SpendBundle;
