from typing import Dict, Type
import importlib


"""
Provides tags for all of the custom objects that can be CBOR encoded
and decoded by src.util.cbor_serialization.
"""

filenames = ["src.protocols.farmer_protocol",
             "src.protocols.plotter_protocol"]

mods = [importlib.import_module(filename) for filename in filenames]

custom_tags: Dict[Type, int] = {}

# Looks at each file in the list
for mod in mods:
    # Grabs all classes from that file
    for _, cls in mod.__dict__.items():
        # If the __tag__ attribute exists (using @cbor_message decorator)
        if hasattr(cls, "__tag__"):
            # Check if tag or class has already been seen, to catch typos
            if cls in custom_tags.keys() or cls.__tag__ in custom_tags.values():
                raise RuntimeError("Class defined twice, or tag defined twice")
            custom_tags[cls] = cls.__tag__
