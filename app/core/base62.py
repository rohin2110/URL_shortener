"""Base62 encoding of non-negative integers (row IDs -> short codes).

Alphabet order is 0-9, a-z, A-Z. Encoding is a bijection between integers >= 0 and
canonical strings (no leading "0" except for "0" itself), so every ID maps to exactly
one code and decode(encode(n)) == n.
"""

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)
_INDEX = {char: i for i, char in enumerate(ALPHABET)}


def encode(number: int) -> str:
    if not isinstance(number, int) or isinstance(number, bool):
        raise TypeError("number must be an int")
    if number < 0:
        raise ValueError("number must be non-negative")
    if number == 0:
        return ALPHABET[0]

    chars: list[str] = []
    while number:
        number, remainder = divmod(number, BASE)
        chars.append(ALPHABET[remainder])
    return "".join(reversed(chars))


def decode(code: str) -> int:
    if not code:
        raise ValueError("code must be non-empty")
    number = 0
    for char in code:
        try:
            number = number * BASE + _INDEX[char]
        except KeyError:
            raise ValueError(f"invalid base62 character: {char!r}") from None
    return number


def is_valid(code: str) -> bool:
    return bool(code) and all(char in _INDEX for char in code)
