from collections import OrderedDict
import copy
from pathlib import Path

import yaml
from yaml.composer import Composer
from yaml.constructor import BaseConstructor, Constructor, FullConstructor, SafeConstructor
from yaml.parser import Parser
from yaml.reader import Reader
from yaml.resolver import BaseResolver, Resolver
from yaml.scanner import Scanner


# remove resolver entries for On/Off/Yes/No
for ch in "OoYyNn":
    if len(Resolver.yaml_implicit_resolvers[ch]) == 1:
        del Resolver.yaml_implicit_resolvers[ch]
    else:
        Resolver.yaml_implicit_resolvers[ch] = [x for x in
                Resolver.yaml_implicit_resolvers[ch] if x[0] != 'tag:yaml.org,2002:bool']


here = Path(__file__).parent


def bool_constructor(self, node):
    print(node)
    return self.construct_scalar(node)

Constructor.add_constructor(u'tag:yaml.org,2002:bool', bool_constructor)

# class OurConstructor(yaml.constructor.Constructor):
#     def __init__(self, *args, **kwargs):
#         # super().__init__(*args, **kwargs)
#
#         self.add_constructor(u'tag:yaml.org,2002:bool', bool_constructor)


# class Loader(Reader, Scanner, Parser, Composer, OurConstructor, Resolver):
#     def __init__(self, stream) -> None: ...
#     # def __init__(self, stream: yaml._ReadStream) -> None: ...


def ordered_dict_representer(dumper, data):
    return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())


def str_representer(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style="")


class TidyOrderedDictDumper(yaml.Dumper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_representer(
            OrderedDict,
            ordered_dict_representer,
        )

        self.add_representer(
            str,
            str_representer,
        )


def main():
    source_path = here.joinpath("workflow.yml")
    output_path = here.parent.joinpath(".github", "workflows", "test.yml")

    with source_path.open() as file:
        source = yaml.safe_load(stream=file)
        # source = yaml.load(stream=file, Loader=Loader)

    output = copy.deepcopy(source)
    del output["jobs"]["test"]

    coverage = output["jobs"].pop("coverage")

    os_matrix = source["jobs"]["test"]["strategy"]["matrix"]["os"]

    coverage["needs"] = []

    for os_entry in os_matrix:
        d = copy.deepcopy(source["jobs"]["test"])
        d["strategy"]["matrix"]["os"] = [os_entry]
        name = f"test_{os_entry['matrix']}"
        output["jobs"][name] = d
        coverage["needs"].append(name)

    output["jobs"]["coverage"] = coverage

    with output_path.open("w") as file:
        yaml.dump(
            data=output,
            stream=file,
            Dumper=TidyOrderedDictDumper,
            sort_keys=False,
        )


main()
