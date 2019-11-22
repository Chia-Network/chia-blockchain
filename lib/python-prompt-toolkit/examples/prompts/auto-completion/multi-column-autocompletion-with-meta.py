#!/usr/bin/env python
"""
Autocompletion example that shows meta-information alongside the completions.
"""
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.shortcuts import CompleteStyle, prompt

animal_completer = WordCompleter([
    'alligator', 'ant', 'ape', 'bat',

    'bear', 'beaver', 'bee', 'bison', 'butterfly', 'cat', 'chicken',
    'crocodile', 'dinosaur', 'dog', 'dolphin', 'dove', 'duck', 'eagle',
    'elephant',
], meta_dict={
    'alligator': 'An alligator is a crocodilian in the genus Alligator of the family Alligatoridae.',
    'ant': 'Ants are eusocial insects of the family Formicidae',
    'ape': 'Apes (Hominoidea) are a branch of Old World tailless anthropoid catarrhine primates ',
    'bat': 'Bats are mammals of the order Chiroptera',
}, ignore_case=True)


def main():
    text = prompt('Give some animals: ', completer=animal_completer,
                  complete_style=CompleteStyle.MULTI_COLUMN)
    print('You said: %s' % text)


if __name__ == '__main__':
    main()
