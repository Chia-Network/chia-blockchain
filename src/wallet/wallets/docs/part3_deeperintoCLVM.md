# Part 3: Deeper into CLVM

This guide directly continues on from [part 1](./part1_basics.md) so if you haven't read that, please do so before reading this.

This section of the guide will cover how ChiaLisp relates to transactions and coins on the Chia network.
If there are any terms that you aren't sure of, be sure to check the [glossary](./glossary.md).


## Lazy Evaluation in ChiaLisp

As we saw in part 1, programs are often structured around `(i A B C)` to control flow.
ChiaLisp evaluates programs as trees, where the leaves are evaluated first.
This can cause unexpected problems if you are not aware of it.
Consider the following program which uses `x` which immediately halts and throws an error if it is evaluated.

```
$ brun '(i (q 1) (q 100) (x (q "still being evaluated")))'
FAIL: clvm raise (0x7374696c6c206265696e67206576616c7561746564)
```

This is because ChiaLisp evaluates both of the leaves even though it will only follow the path of one.

To get around this we can use the following design pattern to replace (i A B C).
```
((c (i (A) (q B) (q C)) (a)))
```
Applying this to our above example looks like this:

```
$ brun '((c (i (q 1) (q (q 100)) (q (x (q "still being evaluated")))) (a)))'
100
```

It is worth keeping this in mind whenever you write an `(i A B C)`.

If you're wondering how this works (and how the standard transaction from [part 2](./part2_transactions.md) worked), then allow me to introduce Eval.

## Introduction to Eval

In [Part 1](part1_basics.md) we mentioned that a program is usually a list where the first element is an operator, and every subsequent element is a valid program.
However a Program can also have a program as the first element. This will cause that program to be evaluated as a new puzzle.
The solution is then every element after the first in this list.

This looks like this:

```
((*puzzle*) *solution* *elements* *go* *here*)
```

In order to create this list we want to use:
```
((c (*puzzle*) (*solution*)))
```

Let's put this into practice.

Here is a program that evaluates the program `(+ (f (a) (q 5)))` and uses the list `(70 80 90)` or `(80 90 100)` as the solution.
```
$ brun '((c (q (+ (f (a)) (q 5))) (q (70 80 90))))' '(20 30 40)'
75

$ brun '((c (q (+ (f (a)) (q 5))) (q (80 90 100))))' '(20 30 40)'
85

```
Notice how the original solution `(20 30 40)` does not matter for the new evaluation environment.
In this example we use `q` to quote both the new puzzle and the new solution to prevent them from being prematurely evaluated.

A neat trick that we can pull is that we can define the new solution in terms of the outer solution.
In this next example we will add the first element of the old solution to our new solution.

```
$ brun '((c (q (+ (f (a)) (q 5))) (c (f (a)) (q (70 80 90)))))' '(20 30 40)'
25
```

However it's not just the new solution that we can affect using this, we can also pass programs as parameters.


## Programs as Parameters

The core CLVM does not allow user defined functions.
It does, however, allow programs to be passed as parameters, which can be used for similar results.

Here is a puzzle that executes the program contained in `(f (a))` with the solution `(12)`.

```
$ brun '((c (f (a)) (q (12))))' '((* (f (a)) (q 2)))'
24
```

Taking this further we can make the puzzle run a new evaluation that only uses parameters from its old solution:

```
$ brun '((c (f (a)) (a)))' '((* (f (r (a)) (q 2))) 10)'
10
```

We can use this technique to implement recursive programs.


## Example: Factorial

Consider the recursive function for a factorial, which is written in pseudo-code below:
```
(i (= (f (a)) (q 1)) (q 1) (* (f (a)) (factorial (- (f (a)) (q 1)))))
```
Overlooking the fact that `factorial` is not an operator, this code contains one other problem. Can you spot it?

It's not using lazy evaluation.
**If you don't force lazy evaluation, your recursive programs will try to evaluate infinitely and crash.**

Here is the fixed pseudo-code using the `((c (i (A) (q B) (q C)) (a)))` pattern:

```
((c (i (= (f (a)) (q 1)) (q (q 1)) (q (* (f (a)) (factorial (- (f (a)) (q 1)))))) (a)))
```

The next step is to replace `factorial`.

While we can't define a new operator, we can encode the factorial function as a parameter and evaluate it as a puzzle.
Let's create a solution where `(f (a))` is our factorial code, and `(f (r (a)))` is the number we are operating on.

When calling the factorial program we want to create a new solution where `(f (r (a)))` is decremented by 1.

It is a good idea when creating ChiaLisp programs to break it down to sub programs, so let's create and test our new solution generating program:

```
$ brun '(c (f (a)) (c (- (f (r (a))) (q 1)) (q ())))' '("source code" 100)'
("source code" 99)
```
Perfect.

We can now use this smaller fragment to construct our finished factorial source code:

```
(((c (i (= (f (r (a))) (q 1)) (q (q 1)) (q (* (f (r (a))) ((c (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (q ())))))))) (a))) *num to factorial*)
```
and we can call it using the puzzle `((c (f (a)) (a)))`

```
$ brun '((c (f (a)) (a)))' '(((c (i (= (f (r (a))) (q 1)) (q (q 1)) (q (* (f (r (a))) ((c (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (q ())))))))) (a))) 5)'
120

$ brun '((c (f (a)) (a)))' '(((c (i (= (f (r (a))) (q 1)) (q (q 1)) (q (* (f (r (a))) ((c (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (q ())))))))) (a))) 6)'
720
```

It works!

But there is one final step. We need to encode this as part of the puzzle.
The above example assumes we have control of the solution.
But in the context of ChiaLisp the puzzle is securing our money, and we cannot trust solution.

## Recursion in Puzzles

We need to create a new eval environment where the program code is passed in - then call that code again as a parameter.
Here we need to

```
((c (q ((c (f (a)) (a)))) (c (q (*program*)) (c (f (a)) (q ())))))
```

Notice that we need to run eval `((c () ()))` twice.
Once to create an environment where the source code exists and once again to run that source code.
If you compare that pattern with the way we constructed the factorial above, you should see the similarity.

So let's finish our factorial program from above using our new pattern.

```
((c (q ((c (f (a)) (a)))) (c (q ((c (i (= (f (r (a))) (q 1)) (q (q 1)) (q (* (f (r (a))) ((c (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (q ())))))))) (a)))) (c (f (a)) (q ())))))
```
And let's test it with clvm_tools
```
$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (= (f (r (a))) (q 1)) (q (q 1)) (q (* (f (r (a))) ((c (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (q ())))))))) (a)))) (c (f (a)) (q ())))))' '(5)'
120
```

We now have a design pattern that allows us to create recursive programs that can be part of smart contracts, and more complicated ChiaLisp puzzles.

In [part 4](./part4_compiler_and_tips.md) we will cover the higher level language, and other tips for smart contract development.
