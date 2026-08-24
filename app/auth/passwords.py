"""密码哈希与策略校验。"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


_PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


def validate_password(password, username=""):
    value = str(password or "")
    if len(value) < 8:
        raise ValueError("密码至少需要 8 个字符")
    if len(value) > 128:
        raise ValueError("密码不能超过 128 个字符")
    if username and username.lower() in value.lower():
        raise ValueError("密码不能包含用户名")
    return value


def hash_password(password, username=""):
    return _PASSWORD_HASHER.hash(validate_password(password, username))


def verify_password(password_hash, password):
    try:
        valid = _PASSWORD_HASHER.verify(str(password_hash or ""), str(password or ""))
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False, False
    return valid, valid and _PASSWORD_HASHER.check_needs_rehash(password_hash)
