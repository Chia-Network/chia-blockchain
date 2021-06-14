import pytest
import io

from chia.util.ints import int8, uint8, int16, uint16, int32, uint32, int64, uint64, uint128, int512


class TestStructStream:
    def _test_impl(self, cls, upper_boundary, lower_boundary):

        with pytest.raises(ValueError):
            t = cls(upper_boundary + 1)

        with pytest.raises(ValueError):
            t = cls(lower_boundary - 1)

        t = cls(upper_boundary)
        assert t == upper_boundary

        t = cls(lower_boundary)
        assert t == lower_boundary

        t = cls(0)
        assert t == 0

    def test_int512(self):
        # int512 is special. it uses 65 bytes to allow positive and negative
        # "uint512"
        self._test_impl(
            int512,
            0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,  # noqa: E501
            -0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,  # noqa: E501
        )

    def test_uint128(self):
        self._test_impl(uint128, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, 0)

    def test_uint64(self):
        self._test_impl(uint64, 0xFFFFFFFFFFFFFFFF, 0)

    def test_int64(self):
        self._test_impl(int64, 0x7FFFFFFFFFFFFFFF, -0x8000000000000000)

    def test_uint32(self):
        self._test_impl(uint32, 0xFFFFFFFF, 0)

    def test_int32(self):
        self._test_impl(int32, 0x7FFFFFFF, -0x80000000)

    def test_uint16(self):
        self._test_impl(uint16, 0xFFFF, 0)

    def test_int16(self):
        self._test_impl(int16, 0x7FFF, -0x8000)

    def test_uint8(self):
        self._test_impl(uint8, 0xFF, 0)

    def test_int8(self):
        self._test_impl(int8, 0x7F, -0x80)

    def test_roundtrip(self):
        def roundtrip(v):
            s = io.BytesIO()
            v.stream(s)
            s.seek(0)
            cls = type(v)
            v2 = cls.parse(s)
            assert v2 == v

        # int512 is special. it uses 65 bytes to allow positive and negative
        # "uint512"
        roundtrip(
            int512(
                0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  # noqa: E501
            )
        )
        roundtrip(
            int512(
                -0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  # noqa: E501
            )
        )

        roundtrip(uint128(0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF))
        roundtrip(uint128(0))

        roundtrip(uint64(0xFFFFFFFFFFFFFFFF))
        roundtrip(uint64(0))

        roundtrip(int64(0x7FFFFFFFFFFFFFFF))
        roundtrip(int64(-0x8000000000000000))

        roundtrip(uint32(0xFFFFFFFF))
        roundtrip(uint32(0))

        roundtrip(int32(0x7FFFFFFF))
        roundtrip(int32(-0x80000000))

        roundtrip(uint16(0xFFFF))
        roundtrip(uint16(0))

        roundtrip(int16(0x7FFF))
        roundtrip(int16(-0x8000))

        roundtrip(uint8(0xFF))
        roundtrip(uint8(0))

        roundtrip(int8(0x7F))
        roundtrip(int8(-0x80))
