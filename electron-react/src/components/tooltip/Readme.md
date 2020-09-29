The Tooltip component is the [default MUI component](https://material-ui.com/components/tooltips/#tooltip) with modified styling.

Tooltip with default styling.

```jsx
import Typography from "@material-ui/core/Typography";
import Link from '@material-ui/core/Link';

<Tooltip
  arrow
  placement="right"
  interactive
  title={
    <div>
      A farm is a group of plots harvested by harvesters.  
      The combined plot sizes create your farms chance of winning the next block. <Link href="#">Learn more</Link>
    </div>
  }
>
  <span>Hover Me</span>
</Tooltip>
```

Tooltip with overridden styling.

```jsx
import Typography from "@material-ui/core/Typography";
import Link from '@material-ui/core/Link';

<Tooltip
  arrow
  placement="bottom"
  interactive
  title={
    <div 
      style={{
        fontFamily: "Consolas",
        fontWeight: 600,
        fontSize: "16px",
    }}>
      Oxa6582dba9bef47f72806d300
    </div>
  }
>
  <span>Oxa658255ba...</span>
</Tooltip>
```