from typing import get_type_hints


def hash_pointer(the_type, hash_f):
    """
    Create a "cryptographic pointer" type that can accept either a hash or an instance
    of the type. It can also reconstruct the underlying the object given a data source.

    The resulting type subclasses the type returned from hash_f.
    """
    hash_type = get_type_hints(hash_f)["return"]

    def __new__(cls, v):
        has_obj = isinstance(v, the_type)
        if has_obj:
            v_ptr = hash_f(bytes(v))
        else:
            v_ptr = v
        r = hash_type.__new__(cls, v_ptr)
        if has_obj:
            r._obj = v
        else:
            r._obj = None
        return r

    async def obj(self, data_source=None):
        """
        Return the underlying object that has the given hash. If it's not already in memory,
        it builds it using the blob from the given data source.
        """
        if self._obj is None and data_source:
            blob = await data_source.hash_preimage(hash=self)
            if blob is not None and hash_f(blob) == self:
                self._obj = the_type.from_bytes(blob)
        return self._obj

    namespace = dict(__new__=__new__, obj=obj)
    hash_pointer_type = type(
        "%sPointer" % the_type.__name__, (hash_type,), namespace)
    return hash_pointer_type
