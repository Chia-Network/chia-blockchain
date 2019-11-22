#!/usr/bin/env python
"""
Example usage of 'print_container', a tool to print
any layout in a non-interactive way.
"""
from prompt_toolkit.shortcuts import print_container
from prompt_toolkit.widgets import Frame, TextArea

print_container(
    Frame(
        TextArea(text='Hello world!\n'),
        title='Stage: parse',
    ))
