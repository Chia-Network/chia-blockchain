# Part 1: CLVM Basics

CLVM is the compiled, minimal version of ChiaLisp that is used by the Chia network.
The full set of operators is documented [here](https://github.com/Chia-Network/clvm/blob/master/docs/clvm.org)

This guide will cover the basics of the language and act as an introduction to the structure of programs.
You should be able to follow along by running a version of [clvm_tools](https://github.com/Chia-Network/clvm_tools).


## Types

In ChiaLisp everything is either a list or an atom.
Lists take the form of parentheses and each entry in the list is single spaced.

Atoms are either literal binary blobs or variables.
**A program is actually just a list in [polish notation](https://en.wikipedia.org/wiki/Polish_notation).**

There is no distinguishing of variable types in ChiaLisp.
This means that `(100 0x65 0x68656c6c6f)` and `(0x64 101 'hello')` are equivalent lists.
Internally however the blobs can be interpreted in a number of different ways, which we will cover later.

## Math

There are no support for floating point numbers in ChiaLisp, only integers.
Internally integers are interpreted as 256 bit signed integers.

The math operators are `*`, `+`, `-`, and `uint64`.

```
$ brun '(- (q 6) (q 5))' '()'
1

$ brun '(* (q 2) (q 4) (q 5))' '()'
40

$ brun '(+ (q 10) (q 20) (q 30) (q 40))' '()'
100

$ $ brun '(uint64 (q 10))' '()'
0x000000000000000a
```

You may have noticed that the multiplication example above takes more than two parameters in the list.
This is because many operators can take variable amounts of parameters.
`+` and `-` are commutative so the order of parameters does not matter.
For non-commutative operations, `(- (q 100) (q 30) (q 20) (q 5))` is equivalent to `(- (q 100) (+ (q 30) (q 20) (q 5)))`.
Similarly, `(/ 120 5 4 2)` is equivalent to `(/ 120 (* 5 4 2))`.

There is also internal support for negatives.

```
$ brun '(- (q 5) (q 7))' '()'
-2


$ brun '(+ (q 3) (q -8))' '()'
-5
```

To use hexadecimal numbers, simply prefix them with `0x`.

```
$ brun '(+ (q 0x000a) (q 0x000b))' '()'
21
```

The final mathematical operator is equal which acts similarly to == in other languages.
```
$ brun '(= (q 5) (q 6))' '()'
()

$ brun '(= (q 5) (q 5))' '()'
1
```

As you can see above this language interprets some data as boolean values.

## Booleans

In this language an empty list `()` evaluate to `False`.
Any other value evaluates to `True`, though internally `True` is represented with `1`.


```
$ brun '(= (q 100) (q 90))' '()'
()

$ brun '(= (q 100) (q 90))' '()'
1
```

The exception to this rule is `0` because `0` is  exactly the same as `()`.

```
$ brun '(= (q 0) (q ()))' '()'
1

$ brun '(+ (q 70) (q ()))' '()'
70
```

## Flow Control

The `i` operator takes the form `(i A B C)` and acts as an `if` statement where `(if A is True then do B, else do C)`.

```
$ brun '(i (q 0) (q 70) (q 80))' '()'
80

$ brun '(i (q 1) (q 70) (q 80))' '()'
70

$ brun '(i (q 12) (q 70) (q 80))' '()'
70

$ brun '(i (q (70 80 90)) (q 70) (q 80))' '()'
70
```

Now seems like a good time to clarify further about lists and programs.


## Lists and Programs

A list is any space-separated, ordered group of one or more elements inside brackets.
For example: `(70 80 90 100)`, `(0xf00dbabe 48 "hello")`, and `(90)` are all valid lists.

Lists can even contain other lists, such as `("list" "list" ("sublist" "sublist" ("sub-sublist")) "list")`.

Programs are a subset of lists which can be evaluated using CLVM.

**In order for a list to be a valid program:**

**1. The first item in the list must be a valid operator**

**2. Every item after the first must be a valid program**

This is why literal values and non-program lists *must* be quoted using `q`.

*Note: There is a special case where the first item in a program is also a program, which we will cover in more detail later.*

Programs can contain non-program lists, but they also must be quoted, for example:

```
$ brun '(q (80 90 100))' '()'
(80 90 100)
```

And now that we know we can have programs inside programs we can create programs such as:

```
$ brun '(i (= (q 50) (q 50)) (+ (q 40) (q 30)) (q 20))' '()'
70
```

Programs in ChiaLisp tend to get built in this fashion.
Smaller programs are assembled together to create a larger program.
It is recommended that you create your programs in an editor with brackets matching!


## List Operators

`f` returns the first element in a passed list.

```
$ brun '(f (q (80 90 100)))' '()'
80
```

`r` returns every element in a list except for the first.

```
$ brun '(r (q (80 90 100)))' '()'
(90 100)
```

`c` prepends an element to a list

```
$ brun '(c (q 70) (q (80 90 100)))' '()'
(70 80 90 100)
```

And we can use combinations of these to access or replace any element we want from a list:

```
$ brun '(c (q 100) (r (q (60 110 120))))' '()'
(100 110 120)

$ brun '(f (r (r (q (100 110 120 130 140)))))' '()'
120
```


## Solutions and Environment Variables

Up until now our programs have not had any input or variables, however ChiaLisp does have support for a kind of variable which is passed in through a solution.

It's important to remember that the context for ChiaLisp is for use in locking up coins with a puzzle program.
This means that we need to be able to pass some information to the puzzle.

A solution is a list passed to the puzzle, and can be referenced with `a`.

```
$ brun '(a)' '("this" "is the" "solution")'
("this" "is the" "solution")

$ brun '(f (a))' '(80 90 100 110)'
80

$ brun '(r (a))' '(80 90 100 110)'
(90 100 110)
```

And remember lists can be nested too.

```
$ brun '(f (f (r (a))))' '((70 80) (90 100) (110 120))'
90

$ brun '(f (f (r (a))))' '((70 80) ((91 92 93 94 95) 100) (110 120))'
(91 92 93 94 95)
```

These environment variables can be used in combination with all other operators.

```
$ brun '(+ (f (a)) (q 5))' '(10)'
15

$ brun '(* (f (a)) (f (a)))' '(10)'
100
```

This program checks that the second variable is equal to the square of the first variable.

```
$ brun '(= (f (r (a))) (* (f (a)) (f (a))))' '(5 25)'
1

$ brun '(= (f (r (a))) (* (f (a)) (f (a))))' '(5 30)'
()
```

## End of Part 1

This marks the end of this section of the guide.
In this section we have covered many of the basics of using ChiaLisp.
It is recommended you play with using the information presented here for a bit before moving on.

This guide has not covered all of the operators available in ChiaLisp - try using some of the other ones listed [here](https://github.com/Chia-Network/clvm/blob/master/docs/clvm.org).

When you are ready, you can move on to [Part 2](./part2_transactions.md).
