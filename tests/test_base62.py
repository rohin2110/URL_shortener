import pytest

from app.core import base62


@pytest.mark.parametrize(
    ("number", "code"),
    [
        (0, "0"),
        (1, "1"),
        (9, "9"),
        (10, "a"),
        (35, "z"),
        (36, "A"),
        (61, "Z"),
        (62, "10"),
        (3843, "ZZ"),
        (3844, "100"),
        (2**63 - 1, "aZl8N0y58M7"),  # max BIGINT
    ],
)
def test_known_values(number: int, code: str) -> None:
    assert base62.encode(number) == code
    assert base62.decode(code) == number


def test_roundtrip() -> None:
    for number in [*range(0, 5000), 123_456_789, 10**18, 2**63 - 1]:
        assert base62.decode(base62.encode(number)) == number


def test_encoding_is_injective() -> None:
    codes = {base62.encode(n) for n in range(20_000)}
    assert len(codes) == 20_000


def test_codes_are_alphanumeric_and_short() -> None:
    code = base62.encode(2**63 - 1)
    assert code.isalnum() and code.isascii()
    assert len(code) <= 11  # fits the 16-char short_code column with room to spare


def test_encode_rejects_negative() -> None:
    with pytest.raises(ValueError):
        base62.encode(-1)


@pytest.mark.parametrize("bad", [1.5, "12", None, True])
def test_encode_rejects_non_int(bad: object) -> None:
    with pytest.raises(TypeError):
        base62.encode(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", "abc-", "a b", "é", "../x"])
def test_decode_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        base62.decode(bad)


def test_is_valid() -> None:
    assert base62.is_valid("aZ09")
    assert not base62.is_valid("")
    assert not base62.is_valid("ab_c")
    assert not base62.is_valid("favicon.ico")
