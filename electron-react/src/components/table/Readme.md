Single-Row Table:

```jsx
<Table
  header={["Total Chia Farmed", "XCH Farming Rewards", "XCH Feed Collected", "Last Height Farmed"]}
  data={[10, 5120, "31.20", 2029]}
/>
```

Using an annotation in a cell:

```jsx
<Table
  header={["Plot Count", "Total Size of Plots", "Total Network Space", "Expected Time to Win"]}
  data={[
    10, 
    "0.10 TiB", 
    { content: "1.72 TiB", annotation: "Best estimate over last 1 hour" }, 
    "25.5 hours"
  ]}
/>
```

Multi-Row Table:

```jsx
<Table
  header={["Challenge Hash", "Height", "Number of Proofs", "Best Estimate"]}
  data={[
    ["Oxa6582dba9bef47f72806d300", 2029, 0, "309536343 seconds"],
    ["Oxa6582dba9bef47f72806d300", 2029, 0, ""],
    ["Oxa6582dba9bef47f72806d300", 2029, 0, ""],
    ["Oxa6582dba9bef47f72806d300", 2029, 0, ""],
    ["Oxa6582dba9bef47f72806d300", 2029, 0, ""],
  ]}
/>
```
