#!/usr/bin/env python
"""
Demonstration of a custom completer class and the possibility of styling
completions independently by passing formatted text objects to the "display"
and "display_meta" arguments of "Completion".
"""
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import CompleteStyle, prompt

animals = [
    'alligator', 'ant', 'ape', 'bat', 'bear', 'beaver', 'bee', 'bison',
    'butterfly', 'cat', 'chicken', 'crocodile', 'dinosaur', 'dog', 'dolphin',
    'dove', 'duck', 'eagle', 'elephant',
]

animal_family = {
    'alligator': 'reptile',
    'ant': 'insect',
    'ape': 'mammal',
    'bat': 'mammal',
    'bear': 'mammal',
    'beaver': 'mammal',
    'bee': 'insect',
    'bison': 'mammal',
    'butterfly': 'insect',
    'cat': 'mammal',
    'chicken': 'bird',
    'crocodile': 'reptile',
    'dinosaur': 'reptile',
    'dog': 'mammal',
    'dolphin': 'mammal',
    'dove': 'bird',
    'duck': 'bird',
    'eagle': 'bird',
    'elephant': 'mammal',
}

family_colors = {
    'mammal': 'ansimagenta',
    'insect': 'ansigreen',
    'reptile': 'ansired',
    'bird': 'ansiyellow',
}

meta = {
    'alligator': HTML('An <ansired>alligator</ansired> is a <u>crocodilian</u> in the genus Alligator of the family Alligatoridae.'),
    'ant': HTML('<ansired>Ants</ansired> are eusocial <u>insects</u> of the family Formicidae.'),
    'ape': HTML('<ansired>Apes</ansired> (Hominoidea) are a branch of Old World tailless anthropoid catarrhine <u>primates</u>.'),
    'bat': HTML('<ansired>Bats</ansired> are mammals of the order <u>Chiroptera</u>.'),
    'bee': HTML('<ansired>Bees</ansired> are flying <u>insects</u> closely related to wasps and ants.'),
    'beaver': HTML('The <ansired>beaver</ansired> (genus Castor) is a large, primarily <u>nocturnal</u>, semiaquatic <u>rodent</u>.'),
    'bear': HTML('<ansired>Bears</ansired> are carnivoran <u>mammals</u> of the family Ursidae.'),
    'butterfly': HTML('<ansiblue>Butterflies</ansiblue> are <u>insects</u> in the macrolepidopteran clade Rhopalocera from the order Lepidoptera.'),
    # ...
}


class AnimalCompleter(Completer):
    def get_completions(self, document, complete_event):
        word = document.get_word_before_cursor()
        for animal in animals:
            if animal.startswith(word):
                if animal in animal_family:
                    family = animal_family[animal]
                    family_color = family_colors.get(family, 'default')

                    display = HTML(
                        '%s<b>:</b> <ansired>(<' + family_color + '>%s</' + family_color + '>)</ansired>'
                        ) % (animal, family)
                else:
                    display = animal

                yield Completion(
                    animal,
                    start_position=-len(word),
                    display=display,
                    display_meta=meta.get(animal)
                )


def main():
    # Simple completion menu.
    print('(The completion menu displays colors.)')
    prompt('Type an animal: ', completer=AnimalCompleter())

    # Multi-column menu.
    prompt('Type an animal: ', completer=AnimalCompleter(),
           complete_style=CompleteStyle.MULTI_COLUMN)

    # Readline-like
    prompt('Type an animal: ', completer=AnimalCompleter(),
           complete_style=CompleteStyle.READLINE_LIKE)


if __name__ == '__main__':
    main()
