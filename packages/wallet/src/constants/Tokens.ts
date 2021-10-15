import { BubbleChart as AsteroidIcon, LocalDrink as WaterIcon, WbSunny as EnergyIcon } from '@material-ui/icons';
import CATToken from '../types/CATToken';

const Tokens: CATToken = [{
  icon: AsteroidIcon,
  symbol: 'AST',
  name: 'Asteroid',
  tail: '783cd84333cacd7e3f6292963b59dd5855ce6a609b9992a60392725a3ed719de',
  description: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.',
}, {
  icon: WaterIcon,
  symbol: 'WAT',
  name: 'Water',
  tail: '28307353c18ef004294d266fbd4a753eef3b60e2c98ba648b271ac277d33073f',
  description: 'Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
}, {
  icon: EnergyIcon,
  symbol: 'ENG',
  name: 'Energy',
  tail: '1c0304430aa61c3448c3effed0e5a13f017ddd53557f84029f047b82097d2ccc',
  description: 'Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.',
}];

export default Tokens;
