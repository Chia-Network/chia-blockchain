import { BubbleChart as AsteroidIcon, LocalDrink as WaterIcon, WbSunny as EnergyIcon } from '@material-ui/icons';
import CATToken from '../types/CATToken';

const Tokens: CATToken = [{
  icon: AsteroidIcon,
  symbol: 'AST',
  name: 'Asteroid',
  tail: '8cbc44d2230d42405df3846f5f124c38a824f96419cecea8ef7f49787e1d05c5',
  description: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.',
}, {
  icon: WaterIcon,
  symbol: 'WAT',
  name: 'Water',
  tail: 'c227d12fbcf14ed3cb66730971117bf7c25f0a14f3c4916a2f9c91dc452fab8e',
  description: 'Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
}, {
  icon: EnergyIcon,
  symbol: 'ENG',
  name: 'Energy',
  tail: '916d3b662263a8afa6fd7b5c0d5c79d6652677a6279217fd667f60a8ee8c83a8',
  description: 'Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.',
}];

export default Tokens;
