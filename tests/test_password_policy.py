import pytest

from app.auth.passwords import validate_password


def test_password_length_boundaries():
    with pytest.raises(ValueError, match="密码至少需要 8 个字符"):
        validate_password("a" * 7)

    assert validate_password("a" * 8) == "a" * 8
    assert validate_password("a" * 128) == "a" * 128

    with pytest.raises(ValueError, match="密码不能超过 128 个字符"):
        validate_password("a" * 129)


def test_password_rejects_username():
    with pytest.raises(ValueError, match="密码不能包含用户名"):
        validate_password("safeuser123", "user")
