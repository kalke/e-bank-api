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


class TransferIn(BaseModel):
    destination_account_id: str = Field(min_length=1, max_length=64)
    amount: str
    memo: str | None = Field(default=None, max_length=280)


class WithdrawIn(BaseModel):
    amount: str


class ConsentIn(BaseModel):
    policy_version: str = Field(min_length=1, max_length=64)


class OnboardingDocumentIn(BaseModel):
    doc_type: Literal["identity_document", "address_proof"]
    pde_extraction_id: str | None = Field(default=None, max_length=128)
    summary: dict[str, Any] | None = None
