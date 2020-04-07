class DPathDict(dict):
    """
    dpath = "dotted path"

    A DPathDict subclass of "dict" that's easy to use with nested dictionaries as values.

    It treats keys with a "." in them as path separators.

    So `d.get_dpath("foo.bar.baz")` is roughly equal to `d.get("foo", {}).get("bar", {}).get("baz", {})`

    And `d.set_dpath("foo.bar.baz", 100)` is roughly equal to
    `d.setdefault("foo", {}).setdefault("bar", {}).setdefault("baz", 100)`
    """

    def __new__(cls, *args, **kwargs):
        return dict.__new__(cls, *args, **kwargs)

    @classmethod
    def to(cls, d):
        if d is None:
            d = {}
        if not isinstance(d, cls):
            d = cls(d)
        return d

    def get_dpath(self, dpath, default=None):
        """
        Split the dpath between "." dots and drill down through nested
        dictionaries, without choking if one is missing.
        """
        components = dpath.split(".")
        v = self
        for _ in components:
            if v is None:
                break
            v = v.get(_)
        r = default if v is None else v
        if isinstance(r, dict):
            r = self.to(r)
        return r

    def set_dpath(self, dpath, v):
        """
        Split the path between "." dots and drill down through nested
        dictionaries, creating empty ones along the way if missing.
        """
        components = dpath.split(".")
        d = self
        for _ in components[:-1]:
            d = d.setdefault(_, dict())
        d[components[-1]] = v

    def _dpath_components(self):
        """
        Iterate over all subpaths (that are not also intermediate dictionaries),
        return the dpath as a list of keys.
        """
        for k in self.keys():
            v = self.get_dpath(k)
            prefix = [k]
            if isinstance(v, dict):
                for _ in v._dpath_components():
                    yield prefix + _
            else:
                yield prefix

    def dpaths(self):
        """
        Iterate over all subpaths (that are not also intermediate dictionaries), returning
        the path as a string.
        """
        for _ in self._dpath_components():
            yield ".".join(_)
