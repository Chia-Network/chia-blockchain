from typing import Any, Type, get_type_hints


class ArgTypeChecker:
    def parse_item(self, a: Any, f_name: str, f_type: Type) -> Any:
        if hasattr(f_type, "__origin__") and f_type.__origin__ == list:
            return [self.parse_item(el, f_type.__args__[0].__name__, f_type.__args__[0]) for el in a]
        if not isinstance(a, f_type):
            try:
                a = f_type.from_bytes(a)
            except TypeError:
                a = f_type(a)
        if not isinstance(a, f_type):
            raise ValueError("wrong type for %s" % f_name)
        return a

    def __init__(self, *args):
        fields = get_type_hints(self)
        la, lf = len(args), len(fields)
        if la != lf:
            raise ValueError("got %d and expected %d args" % (la, lf))
        for a, (f_name, f_type) in zip(args, fields.items()):
            object.__setattr__(self, f_name, self.parse_item(a, f_name, f_type))


