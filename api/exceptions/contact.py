
from api.exceptions.app import AppException, ErrorTypes


class ContactNotFoundException(AppException):
    def __init__(self, contact_id: int) -> None:
        super().__init__(
            ErrorTypes.ResourceNotFound,
            f"Contact with id {contact_id} not found",
            resource="contact",
            field="id",
            value=str(contact_id),
        )


class ContactDatabaseError(AppException):
    def __init__(
        self, message: str = "A database error occurred while processing the request"
    ) -> None:
        super().__init__(
            ErrorTypes.InternalError,
            message,
            resource="contact",
        )