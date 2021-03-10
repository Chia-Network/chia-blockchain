import Unit from './Unit';
import { IS_MAINNET } from './constants';

export default {
  [Unit.CHIA]: IS_MAINNET ? 'XCH' : 'TXCH',
};
