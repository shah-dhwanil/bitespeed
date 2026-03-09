from typing import Any, Optional
from pydantic import BaseModel, Field


class HTTPDetail(BaseModel):
    type: str = Field(description="Type of the error detail")
    message: str = Field(description="Detailed message about the error")
    resource: Optional[str] = Field(
        default=None, description="Resource associated with the error"
    )
    field: Optional[str] = Field(
        default=None, description="Field associated with the error"
    )
    value: Optional[Any] = Field(
        default=None, description="Value that caused the error, if applicable"
    )


class HTTPException(BaseModel):
    status_code: int = Field(description="HTTP status code of the error")
    title: str = Field(description="Short title describing the error")
    detail: str = Field(description="Detailed description of the error")
    errors: list[HTTPDetail] = Field(description="List of detailed error information")