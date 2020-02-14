"""
A calculator based on https://en.wikipedia.org/wiki/Reverse_Polish_notation
"""

from __future__ import print_function


def getPrec(c):
    if c in "+-":
        return 1
    if c in "*/":
        return 2
    if c in "^":
        return 3
    return 0

def getAssoc(c):
    if c in "+-*/":
        return "LEFT"
    if c in "^":
        return "RIGHT"
    return "LEFT"

def getBin(op, a, b):
    if op == '+':
        return a + b
    if op == '-':
        return a - b
    if op == '*':
        return a * b
    if op == '/':
        return a / b
    if op == '^':
        return a ** b
    return 0

def calc(s):
    numStk = []
    opStk = []
    i = 0
    isUnary = True
    while (i < len(s)):
        while (i < len(s) and s[i] == ' '):
            i += 1
        if (i >= len(s)):
            break
        if (s[i].isdigit()):
            num = ''
            while (i < len(s) and (s[i].isdigit() or s[i] == '.')):
                num += s[i]
                i += 1
            numStk.append(float(num))
            isUnary = False
            continue

        if (s[i] in "+-*/^"):
            if isUnary:
                opStk.append('#')
            else:
                while (len(opStk) > 0):
                    if ((getAssoc(s[i]) == "LEFT" and getPrec(s[i]) <= getPrec(opStk[-1])) or 
                        (getAssoc(s[i]) == "RIGHT" and getPrec(s[i]) < getPrec(opStk[-1]))):
                        op = opStk.pop()
                        if op == '#':
                            numStk.append(-numStk.pop())
                        else:
                            b = numStk.pop()
                            a = numStk.pop()
                            numStk.append(getBin(op, a, b))
                        continue
                    break
                opStk.append(s[i])
            isUnary = True
        elif (s[i] == '('):
            opStk.append(s[i])
            isUnary = True
        else:
            while (len(opStk) > 0):
                op = opStk.pop()
                if (op == '('):
                    break
                if op == '#':
                    numStk.append(-numStk.pop())
                else:
                    b = numStk.pop()
                    a = numStk.pop()
                    numStk.append(getBin(op, a, b))
        i += 1

    while (len(opStk) > 0):
        op = opStk.pop()
        if op == '#':
            numStk.append(-numStk.pop())
        else:
            b = numStk.pop()
            a = numStk.pop()
            numStk.append(getBin(op, a, b))

    return numStk.pop()
    

if __name__ == '__main__':
    ss = [
        "1 + 2 * 3 / 4 - 5 + - 6", # -8.5
        "10 + ( - 1 ) ^ 4", # 11
        "10 + - 1 ^ 4", # 9
        "10 + - - 1 ^ 4", # 11
        "10 + - ( - 1 ^ 4 )", # 11
        "5 * ( 10 - 9 )", # 5
        "1 + 2 * 3", # 7
        "4 ^ 3 ^ 2", # 262144
        "4 ^ - 3", # 0.015625
        "4 ^ ( - 3 )", # 0.015625
    ]
    for s in ss:
        res = calc(s)
        print('{} = {}'.format(res, s))
    