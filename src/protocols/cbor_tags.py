from typing import Dict, Type
from collections import ChainMap
import importlib


"""
Provides tags for all of the custom objects that can be CBOR encoded
and decoded by src.util.cbor_serialization.
"""

filenames = ["src.protocols.farmer_protocol",
             "src.protocols.plotter_protocol"]

mods = [importlib.import_module(filename)
        for filename in filenames]

custom_tags_separate = [dict([(cls, cls.__tag__) for _, cls in mod.__dict__.items()
                              if hasattr(cls, "__tag__")]) for mod in mods]

custom_tags: Dict[Type, int] = dict(ChainMap(*custom_tags_separate))
