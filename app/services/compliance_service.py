from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import AppError
from app.models.suppression import VoiceSuppressionList


class ComplianceService:
    E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def validate_outbound_test_call(self, db: Session, to: str) -> None:
        if not self.E164_PATTERN.match(to):
            raise AppError(
                "INVALID_PHONE_NUMBER",
                "Phone number must use E.164 format, for example +56912345678.",
                status_code=422,
            )

        suppressed = db.execute(
            select(VoiceSuppressionList).where(VoiceSuppressionList.phone_normalized == to)
        ).scalar_one_or_none()
        if suppressed:
            raise AppError(
                "NUMBER_SUPPRESSED",
                "This phone number is blocked by the suppression list.",
                status_code=403,
            )

        if to != self.settings.allowed_test_number:
            raise AppError(
                "OUTBOUND_CALL_BLOCKED",
                "MVP mode only allows calls to ALLOWED_TEST_NUMBER. Cold calling, campaigns, and other numbers are blocked.",
                status_code=403,
            )
