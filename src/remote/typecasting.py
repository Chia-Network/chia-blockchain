from typing import Any, Callable, Dict, List, Type


def recast_to_type(
    value: Any, the_type: Type, cast_simple_type: Callable[[Any, Type], Any]
):
    """
    Take the given value `value`, and recast it to type `the_type`, using `cast_simple_type`,
    drilling down through the hierarchy if necessary.
    """

    origin = getattr(the_type, "__origin__", None)

    if origin is dict:
        key_type, value_type = the_type.__args__
        return {
            recast_to_type(k, key_type, cast_simple_type): recast_to_type(
                v, value_type, cast_simple_type
            )
            for k, v in value.items()
        }

    if origin is list:
        value_type = the_type.__args__[0]
        return list(recast_to_type(_, value_type, cast_simple_type) for _ in value)

    return cast_simple_type(value, the_type)


def recast_arguments(
    annotations: Dict[str, Type],
    cast_simple_type: Callable[[Any, Type], Any],
    args: List[Any],
    kwargs: Dict[str, Any],
):
    """
    Returns `args`, `kwargs`, using the annotation hints and cast function.
    """

    cast_args = [
        recast_to_type(v, t, cast_simple_type)
        for v, t in zip(args, annotations.values())
    ]

    cast_kwargs = {}

    for k, t in kwargs.items():
        kw = kwargs[k]
        annotation = annotations.get(k)
        if annotation is None:
            raise ValueError("Annotation is None")
        cast_kwargs[k] = recast_to_type(kw, annotation, cast_simple_type)

    return cast_args, cast_kwargs
