import { BubbleChart as AsteroidIcon, LocalDrink as WaterIcon, WbSunny as EnergyIcon } from '@material-ui/icons';
import CATToken from '../types/CATToken';

const Tokens: CATToken = [{
  icon: AsteroidIcon,
  symbol: 'AST',
  name: 'Asteroid',
  tail: 'e656d039dc76dbf5354a4932aafe1b25fc10119e4d747499938d6f552564d1e5',
  description: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.',
}, {
  icon: WaterIcon,
  symbol: 'WAT',
  name: 'Water',
  tail: '5dd58cab46eb4dccf5dbed297945881631e70727b1800d605cbab7b531039179',
  description: 'Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
}, {
  icon: EnergyIcon,
  symbol: 'ENG',
  name: 'Energy',
  tail: '2b3927c42df28492b38ae16ee956302cd27718e6c71dea13efd523ef1e3250ed',
  description: 'Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.',
}];

export default Tokens;
