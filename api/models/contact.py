from typing import Optional

from pydantic import BaseModel, Field, model_validator
from pydantic import EmailStr
from pydantic_extra_types.phone_numbers import PhoneNumber

PhoneNumber.default_region_code = "IN"  # Default to IN for parsing/validation if no country code provided
PhoneNumber.phone_format = "E164"  # Store/return in E.164 format for consistency

class IdentifyRequest(BaseModel):
    email: Optional[EmailStr] = Field(default=None, description="Customer email address")
    phoneNumber: Optional[PhoneNumber] = Field(
        default=None, description="Customer phone number"
    )

    @model_validator(mode="after")
    def at_least_one_field_required(self) -> "IdentifyRequest":
        if self.email is None and self.phoneNumber is None:
            raise ValueError(
                "At least one of 'email' or 'phoneNumber' must be provided"
            )
        return self


class ConsolidatedContact(BaseModel):
    # Note: 'primaryContatcId' matches the spec spelling exactly (one 't' in Contatc)
    primaryContatcId: int = Field(description="ID of the primary contact")
    emails: list[EmailStr] = Field(
        description="All known emails for this identity; primary's email is first"
    )
    phoneNumbers: list[PhoneNumber] = Field(
        description="All known phone numbers for this identity; primary's phone is first"
    )
    secondaryContactIds: list[int] = Field(
        description="IDs of all secondary contacts linked to the primary"
    )


class IdentifyResponse(BaseModel):
    contact: ConsolidatedContact
