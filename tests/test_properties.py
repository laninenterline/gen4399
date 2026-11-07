"""基于 hypothesis 的属性测试（未安装 hypothesis 时自动跳过）。"""

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, strategies as st  # noqa: E402

from gen4399 import (  # noqa: E402
    USERNAME_CHARSET,
    generate,
    generate_many,
    generate_username,
    parse_profile_line,
    validate,
    validate_username,
)
from gen4399.identity import InvalidProfileError  # noqa: E402


@given(st.integers(min_value=6, max_value=20))
def test_generated_passwords_are_valid(length):
    assert validate(generate(length=length)) == []


@given(st.integers(min_value=6, max_value=20))
def test_generated_usernames_are_valid(length):
    assert validate_username(generate_username(length=length)) == []


@given(st.integers(min_value=1, max_value=50))
def test_batch_unique(count):
    items = generate_many(count, unique=True)
    assert len(set(items)) == count
    assert all(validate(pw) == [] for pw in items)


@given(st.text(alphabet=USERNAME_CHARSET, min_size=6, max_size=12))
def test_username_validator_accepts_generated_alphabet(name):
    assert validate_username(name) == []


@given(st.text(min_size=0, max_size=40))
def test_parse_profile_line_never_crashes_random_text(text):
    try:
        parse_profile_line(text)
    except (InvalidProfileError, ValueError):
        pass
