# Part 4: The Compiler and Other Useful Information

In this part of the guide we will cover the compiler, some more examples, and some high level tips for creating programs in ChiaLisp.

## The Compiler

To compile this higher level language in terminal. Firstly install and set up the latest version of [clvm_tools](https://github.com/Chia-Network/clvm_tools).

To compile use:
```
$ run -s2 '(mod (*var names*) (*high level code*))'
```
The compiler has a number of tools that can make writing complex programs more manageable.

### Naming Variables
With variable names it is possible to name the elements that you expect in the solution list.

```
$ run -s2 '(mod (listOfNumbers listOfStrings listOfHex) (c listOfNumbers (c listOfStrings (c listOfHex (q ())))))'
(c (f (a)) (c (f (r (a))) (c (f (r (r (a)))) (q ()))))

$ brun '(c (f (a)) (c (f (r (a))) (c (f (r (r (a)))) (q ()))))' '((60 70 80) ("list" "of" "strings") (0xf00dbabe 0xdeadbeef 0xbadfeed1))'
((60 70 80) ("list" 28518 "strings") (0xf00dbabe 0xdeadbeef 0xbadfeed1))
```

### Extra Operator: (qq) and (unquote)

When creating Chialisp programs that return dynamically created Chialisp programs, the complexity can increase quickly.
One way we can mitigate this when developing Chialisp is by using quasiquote. 
This is a compiler tool that allows us to use quote and 'unquote' when we want to insert a dynamically created element.

For example let's suppose we are creating a program that returns a program which simply quotes an address.
The base instinct may be to write something like:
```
(q (q 0xdeadbeef))
```
Which when ran, does create a program as expected.
```
$ brun '(q (q 0xdeadbeef))'
(q 0xdeadbeef)
```
But what about if we want to generate the address dynamically by running `(sha256 (f (a)))`?
We couldn't put that inside the outer `q` as it would not be evaluated, and the returned program would be incorrect.

For this we can use `(qq)` and `(unquote)` in the compiler:
```
$ run '(mod (x0 x1) (qq (q (unquote (sha256 x0)))))'
(c (q 1) (c (sha256 (f (a))) (q ())))
```
And running this results in:
```
$ brun '(c (q 1) (c (sha256 (f (a))) (q ())))' '("hello")'
(q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)
```
This is quite a simple example, but when you are creating more complex programs that return dynamically created programs `quasiquote` can become very handy.

### Extra Operator: (list)

If we want to create a list during evaluation, you may have noticed we use `(c (A) (c (B) (c (C) (q ()))))`.
This pattern gets messy and hard to follow if extended further than one or two elements.
In the compiler there is support for an extremely convenient operator that creates these complex `c` structures for us.

```
$ run -s2 '(mod (first second) (list 80 first 30 second))' '()'
(c (q 80) (c (f (a)) (c (q 30) (c (f (r (a))) (q ())))))

$ brun '(c (q 80) (c (f (a)) (c (q 30) (c (f (r (a))) (q ())))))' '(120 160)'
(80 120 30 160)
```

Let's put these compiler tricks to use and demonstrate another useful kind of program.

## Iterating Through a List

One of the best uses for recursion is ChiaLisp is looping through a list.

Let's make a program will sum a list of numbers.
Remember `() == 0 == False`

Here we will use `source` to refer to `(f (a))`, and `numbers` to refer to `(f (r (a)))`.

```
(i numbers (+ (f numbers) ((c source (list source (r numbers))))) (q 0))
```
See how much more readable that is?

Let's compile it.
```
$ run -s2 '(mod (source numbers) (i numbers (+ (f numbers) ((c source (list source (r numbers))))) (q 0)))'
(i (f (r (a))) (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ())))))) (q ()))
```

But remember, we need to use lazy evaluation, so let's update that.

```
((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))
```

The next step is to plug it in to our recursive program pattern from [part 3](part3_deeperintoCLVM.md)
```
((c (q ((c (f (a)) (a)))) (c (q (*program*)) (c (f (a)) (q ())))))
```

So the final puzzle for summing a list of numbers in a solution looks like this

```
((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))
```

We now have a program that will sum a list of numbers that works whatever the size of the list.

```
$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((70 80 90 100))'
340

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((35 128 44 100))'
307

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((35))'
35

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '(())'
()

$ brun '((c (q ((c (f (a)) (a)))) (c (q ((c (i (f (r (a))) (q (+ (f (f (r (a)))) ((c (f (a)) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (q ()))) (a)))) (c (f (a)) (q ())))))' '((100 100 100 100 100 100))'
600
```

