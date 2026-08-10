from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EventIn(BaseModel):
    type: Literal["deposit", "withdraw", "transfer"]
    origin: str | None = None
    destination: str | None = None
    amount: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_fields_by_type(self) -> "EventIn":
        if self.type == "deposit" and not self.destination:
            raise ValueError("destination is required for deposit")
        if self.type == "withdraw" and not self.origin:
            raise ValueError("origin is required for withdraw")
        if self.type == "transfer":
            if not self.origin:
                raise ValueError("origin is required for transfer")
            if not self.destination:
                raise ValueError("destination is required for transfer")
        return self


class DemoMetaOut(BaseModel):
    demo: bool = True
    welcome_amount: str
    currency: str
    disclaimer: str
    features: list[str]


class DemoAccountOut(BaseModel):
    id: str
    balance: str
    currency: str
    kind: str
    status: str
    onboarding_status: str
    demo_credited: bool
    demo: bool = True
    account_number: int | None = None
    digit: int | None = None
    display_number: str | None = None
    holder_name: str | None = None


class TransferIn(BaseModel):
    amount: str
    destination_account_id: str | None = Field(default=None, max_length=64)
    destination_account: str | None = Field(default=None, max_length=32)
    destination_document: str | None = Field(default=None, max_length=32)
    memo: str | None = Field(default=None, max_length=280)

    @model_validator(mode="after")
    def one_destination(self) -> "TransferIn":
        provided = [
            bool(self.destination_account_id),
            bool(self.destination_account),
            bool(self.destination_document),
        ]
        if sum(provided) != 1:
            raise ValueError(
                "provide exactly one of destination_account_id, "
                "destination_account, or destination_document"
            )
        return self


class TransferResolveIn(BaseModel):
    account: str | None = Field(default=None, max_length=32)
    document: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def one_of(self) -> "TransferResolveIn":
        if bool(self.account) == bool(self.document):
            raise ValueError("provide exactly one of account or document")
        return self


class WithdrawIn(BaseModel):
    amount: str


class ConsentIn(BaseModel):
    policy_version: str = Field(min_length=1, max_length=64)


class OnboardingDocumentIn(BaseModel):
    doc_type: Literal["identity_document", "address_proof"]
    pde_extraction_id: str | None = Field(default=None, max_length=128)
    summary: dict[str, Any] | None = None


class OnboardingCompleteIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=256)
    birth_date: date
    document_number: str = Field(min_length=11, max_length=18)
    cep: str = Field(min_length=8, max_length=9)
    street: str = Field(min_length=1, max_length=256)
    number: str = Field(min_length=1, max_length=32)
    complement: str | None = Field(default=None, max_length=128)
    neighborhood: str | None = Field(default=None, max_length=128)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=2)
    email: str = Field(min_length=3, max_length=320)
    phone: str = Field(min_length=10, max_length=20)
    terms_accepted: bool = True
    accepted_at: str | None = None
