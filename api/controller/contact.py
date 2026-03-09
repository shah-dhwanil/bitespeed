from fastapi import APIRouter

from api.models.contact import IdentifyRequest, IdentifyResponse
from api.service.contact import identify_contact

router = APIRouter(prefix="/identify", tags=["Identity"])


@router.post("", response_model=IdentifyResponse, status_code=200)
async def identify(request: IdentifyRequest) -> IdentifyResponse:
    """
    Identify and consolidate a customer contact.

    Accepts an email and/or phone number, links any matching contact records
    into a single identity cluster, and returns the consolidated view.
    """
    return await identify_contact(
        email=request.email,
        phone_number=request.phoneNumber,
    )
