Card with Icon & Button:

```jsx
import FarmIcon from "../../assets/img/noun_Farm.svg";
import Link from '@material-ui/core/Link';

<Card 
  actionText="Add a Plot" 
  onAction={() => {console.log("Add a Plot!")}} 
  iconSrc={FarmIcon}
>
  Farmers earn block rewards and transaction fees by committing spare space to the network to help secure transactions. This is where your farm will be once you add a plot. <Link href="#">Learn more</Link>
</Card>
```

Card with only Button:

```jsx
import Link from '@material-ui/core/Link';

<Card 
  actionText="Add a Plot" 
  onAction={() => {console.log("Add a Plot!")}} 
>
  Farmers earn block rewards and transaction fees by committing spare space to the network to help secure transactions. This is where your farm will be once you add a plot. <Link href="#">Learn more</Link>
</Card>
```

Card with only Icon:

```jsx
import FarmIcon from "../../assets/img/noun_Farm.svg";
import Link from '@material-ui/core/Link';

<Card 
  iconSrc={FarmIcon}
>
  Farmers earn block rewards and transaction fees by committing spare space to the network to help secure transactions. This is where your farm will be once you add a plot. <Link href="#">Learn more</Link>
</Card>
```

Card with only Text:

```jsx
import Link from '@material-ui/core/Link';

<Card>
  Farmers earn block rewards and transaction fees by committing spare space to the network to help secure transactions. This is where your farm will be once you add a plot. <Link href="#">Learn more</Link>
</Card>
```
