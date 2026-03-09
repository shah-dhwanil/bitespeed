from typing import Union

from fastapi import Request, status
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from api.exceptions.app import AppException, ErrorTypes
from api.models.errors import HTTPDetail
from api.models.errors import HTTPException as HTTPExceptionModel


def get_status_code_from_error_type(error_type: ErrorTypes) -> int:
    """Map ErrorTypes to HTTP status codes."""
    status_code_map = {
        ErrorTypes.InputValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        ErrorTypes.ResourceAlreadyExists: status.HTTP_409_CONFLICT,
        ErrorTypes.ResourceNotFound: status.HTTP_404_NOT_FOUND,
        ErrorTypes.InvalidOperation: status.HTTP_400_BAD_REQUEST,
        ErrorTypes.NotEnoughPermission: status.HTTP_403_FORBIDDEN,
        ErrorTypes.ExternalServiceError: status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorTypes.InternalError: status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorTypes.UnkownError: status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorTypes.UnauthorizedOperation: status.HTTP_403_FORBIDDEN,
    }
    return status_code_map.get(error_type, status.HTTP_500_INTERNAL_SERVER_ERROR)


def get_title_from_status_code(status_code: int) -> str:
    """Get a human-readable title from HTTP status code."""
    title_map = {
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        422: "Unprocessable Entity",
        500: "Internal Server Error",
        502: "Bad Gateway",
    }
    return title_map.get(status_code, "Error")


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom AppException instances."""
    status_code = get_status_code_from_error_type(exc.type)

    # Create error details
    errors = [
        HTTPDetail(
            type=exc.type,
            message=exc.message,
            resource=exc.resource,
            field=exc.field,
            value=exc.value,
        )
    ]

    error_response = HTTPExceptionModel(
        status_code=status_code,
        title=get_title_from_status_code(status_code),
        detail=exc.message,
        errors=errors,
    )

    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(exclude_none=True),
    )


async def validation_exception_handler(
    request: Request, exc: Union[RequestValidationError, ValidationError]
) -> JSONResponse:
    """Handle Pydantic and FastAPI validation errors."""
    errors = []

    for error in exc.errors():
        # Extract field path
        field_path = ".".join(str(loc) for loc in error.get("loc", []))

        # Get the error message
        error_msg = error.get("msg", "Validation error")

        # Get the input value if available
        error_input = error.get("input")

        errors.append(
            HTTPDetail(
                type=error.get("type", ErrorTypes.InputValidationError.value),
                message=error_msg,
                field=field_path if field_path else None,
                value=error_input,
            )
        )

    error_response = HTTPExceptionModel(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        title="Validation Error",
        detail="One or more fields failed validation",
        errors=errors,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response.model_dump(exclude_none=True),
    )


async def fastapi_http_exception_handler(
    request: Request, exc: FastAPIHTTPException
) -> JSONResponse:
    """Handle FastAPI's built-in HTTPException."""
    # Determine error type based on status code
    error_type = ErrorTypes.UnkownError
    if exc.status_code == 404:
        error_type = ErrorTypes.ResourceNotFound
    elif exc.status_code == 403:
        error_type = ErrorTypes.NotEnoughPermission
    elif exc.status_code == 400:
        error_type = ErrorTypes.InvalidOperation
    elif exc.status_code == 409:
        error_type = ErrorTypes.ResourceAlreadyExists
    elif exc.status_code >= 500:
        error_type = ErrorTypes.InternalError

    errors = [
        HTTPDetail(
            type=error_type,
            message=str(exc.detail),
            resource=request.url.path,
        )
    ]

    error_response = HTTPExceptionModel(
        status_code=exc.status_code,
        title=get_title_from_status_code(exc.status_code),
        detail=str(exc.detail),
        errors=errors,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(exclude_none=True),
        headers=exc.headers,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle any unhandled exceptions."""
    # Log the exception here (you might want to add proper logging)
    print(f"Unhandled exception: {type(exc).__name__}: {str(exc)}")

    errors = [
        HTTPDetail(
            type=ErrorTypes.InternalError,
            message="An unexpected error occurred. Please try again later.",
            resource=request.url.path,
        )
    ]

    error_response = HTTPExceptionModel(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        detail="An unexpected error occurred",
        errors=errors,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump(exclude_none=True),
    )


def register_exception_handlers(app) -> None:
    """
    Register all exception handlers with the FastAPI application.

    Usage:
        from fastapi import FastAPI
        from api.exceptions.handler import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.add_exception_handler(FastAPIHTTPException, fastapi_http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)