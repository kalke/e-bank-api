"""Shared validation helpers for onboarding (API source of truth)."""

from __future__ import annotations

import re
from datetime import date

from app.errors import OnboardingError

_CEP_RE = re.compile(r"^\d{8}$")
_PHONE_RE = re.compile(r"^\d{10,11}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def validate_cep(cep: str) -> str:
    cleaned = digits_only(cep)
    if not _CEP_RE.match(cleaned):
        raise OnboardingError("invalid CEP")
    return cleaned


def validate_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise OnboardingError("invalid email")
    return cleaned


def validate_phone(phone: str) -> str:
    cleaned = digits_only(phone)
    if not _PHONE_RE.match(cleaned):
        raise OnboardingError("invalid phone")
    return cleaned


def validate_cpf(cpf: str) -> str:
    cleaned = digits_only(cpf)
    if len(cleaned) != 11 or cleaned == cleaned[0] * 11:
        raise OnboardingError("invalid CPF")
    nums = [int(c) for c in cleaned]
    s1 = sum(n * w for n, w in zip(nums[:9], range(10, 1, -1)))
    d1 = (s1 * 10 % 11) % 10
    if d1 != nums[9]:
        raise OnboardingError("invalid CPF")
    s2 = sum(n * w for n, w in zip(nums[:10], range(11, 1, -1)))
    d2 = (s2 * 10 % 11) % 10
    if d2 != nums[10]:
        raise OnboardingError("invalid CPF")
    return cleaned


def validate_cnpj(cnpj: str) -> str:
    cleaned = digits_only(cnpj)
    if len(cleaned) != 14 or cleaned == cleaned[0] * 14:
        raise OnboardingError("invalid CNPJ")
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    nums = [int(c) for c in cleaned]
    d1 = sum(n * w for n, w in zip(nums[:12], weights1)) % 11
    d1 = 0 if d1 < 2 else 11 - d1
    if d1 != nums[12]:
        raise OnboardingError("invalid CNPJ")
    d2 = sum(n * w for n, w in zip(nums[:13], weights2)) % 11
    d2 = 0 if d2 < 2 else 11 - d2
    if d2 != nums[13]:
        raise OnboardingError("invalid CNPJ")
    return cleaned


def validate_document(document: str) -> tuple[str, str]:
    cleaned = digits_only(document)
    if len(cleaned) == 11:
        return "cpf", validate_cpf(cleaned)
    if len(cleaned) == 14:
        return "cnpj", validate_cnpj(cleaned)
    raise OnboardingError("document must be CPF or CNPJ")


def age_years(birth_date: date, *, today: date | None = None) -> int:
    today = today or date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def require_adult(birth_date: date, *, today: date | None = None) -> date:
    if age_years(birth_date, today=today) < 18:
        raise OnboardingError("applicant must be at least 18 years old")
    return birth_date


def mask_document(document: str | None) -> str | None:
    if not document:
        return None
    cleaned = digits_only(document)
    if len(cleaned) == 11:
        return f"***.***.***-{cleaned[-2:]}"
    if len(cleaned) >= 4:
        return f"{'*' * (len(cleaned) - 4)}{cleaned[-4:]}"
    return "****"


def parse_account_display(value: str) -> tuple[int, int]:
    raw = (value or "").strip()
    if "-" in raw:
        left, right = raw.rsplit("-", 1)
        return int(digits_only(left)), int(digits_only(right))
    digits = digits_only(raw)
    if len(digits) < 2:
        raise OnboardingError("invalid account number")
    return int(digits[:-1]), int(digits[-1])


def format_account_display(number: int, digit: int) -> str:
    return f"{int(number):06d}-{int(digit)}"
