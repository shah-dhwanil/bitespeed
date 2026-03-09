from enum import StrEnum
from typing import Optional, Any


class ErrorTypes(StrEnum):
    InputValidationError = "VALIDATION_ERROR"
    ResourceAlreadyExists = "RESOURCE_ALREADY_EXISTS"
    ResourceNotFound = "RESOURCE_NOT_FOUND"
    InvalidOperation = "INVALID_OPERATION"
    UnauthorizedOperation = "UNAUTHORIZED_OPERATION"
    NotEnoughPermission = "NOT_ENOUGH_PERMISSION"
    ExternalServiceError = "EXTERNAL_SERVICE_ERROR"
    InternalError = "INTERNAL_ERROR"
    UnkownError = "UNKNOWN_ERROR"


class AppException(Exception):
    """Base class for all application-specific exceptions."""

    def __init__(
        self,
        type: ErrorTypes,
        message: str,
        resource: Optional[str] = None,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        **kwargs,
    ) -> None:
        self.type = type
        self.message = message
        self.resource = resource
        self.field = field
        self.value = value
        self.context = kwargs
        super().__init__(f"{type}: {message}")


class UnkownAppException(AppException):
    def __init__(self, message: str = "An unknown error occurred", **kwargs) -> None:
        super().__init__(ErrorTypes.UnkownError, message, **kwargs)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized access", **kwargs) -> None:
        super().__init__(ErrorTypes.UnauthorizedOperation, message, **kwargs)

