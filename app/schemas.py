from typing import Literal

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


class AccountOut(BaseModel):
    id: str
    balance: int


class DepositResponse(BaseModel):
    destination: AccountOut


class WithdrawResponse(BaseModel):
    origin: AccountOut


class TransferResponse(BaseModel):
    origin: AccountOut
    destination: AccountOut
