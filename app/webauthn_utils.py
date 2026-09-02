"""
Wraps the `webauthn` package. Uses discoverable credentials (resident keys)
so passkey login needs no username/PIN field — the authenticator itself
tells us which credential (and therefore which user) is being used.
"""
import json
import secrets
from datetime import datetime, timezone

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    base64url_to_bytes,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from webauthn.helpers import (
    bytes_to_base64url,
    parse_registration_credential_json,
    parse_authentication_credential_json,
)

from app.config import rp_id, settings
from app.database import get_db, now_iso

CHALLENGE_TTL_SECONDS = 300


def _store_challenge(challenge_id: str, user_id, challenge: bytes, kind: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO webauthn_challenges (id, user_id, challenge, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (challenge_id, user_id, bytes_to_base64url(challenge), kind, now_iso()),
        )


def _pop_challenge(challenge_id: str, kind: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM webauthn_challenges WHERE id=? AND kind=?", (challenge_id, kind)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM webauthn_challenges WHERE id=?", (challenge_id,))
        return row


def build_registration_options(user_id: int, user_name: str):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT credential_id FROM passkeys WHERE user_id=?", (user_id,)
        ).fetchall()
    exclude = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(row["credential_id"]))
        for row in existing
    ]

    options = generate_registration_options(
        rp_id=rp_id(),
        rp_name=settings.RP_NAME,
        user_id=str(user_id).encode(),
        user_name=user_name,
        user_display_name=user_name,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    challenge_id = secrets.token_urlsafe(16)
    _store_challenge(challenge_id, user_id, options.challenge, "registration")
    return challenge_id, json.loads(options_to_json(options))


def verify_registration(challenge_id: str, credential_json: dict, user_id: int, key_name: str):
    row = _pop_challenge(challenge_id, "registration")
    if not row or row["user_id"] != user_id:
        raise ValueError("Registration challenge expired or invalid")

    credential = parse_registration_credential_json(json.dumps(credential_json))
    verification = verify_registration_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(row["challenge"]),
        expected_rp_id=rp_id(),
        expected_origin=settings.BASE_URL.rstrip("/"),
    )

    with get_db() as conn:
        conn.execute(
            "INSERT INTO passkeys (user_id, name, credential_id, public_key, sign_count, "
            "transports, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                key_name,
                bytes_to_base64url(verification.credential_id),
                bytes_to_base64url(verification.credential_public_key),
                verification.sign_count,
                json.dumps(credential_json.get("response", {}).get("transports", [])),
                now_iso(),
            ),
        )
    return True


def build_authentication_options():
    """Discoverable-credential flow: no allowCredentials, so any passkey
    registered for this RP can be offered by the browser/authenticator."""
    options = generate_authentication_options(
        rp_id=rp_id(),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    challenge_id = secrets.token_urlsafe(16)
    _store_challenge(challenge_id, None, options.challenge, "authentication")
    return challenge_id, json.loads(options_to_json(options))


def verify_authentication(challenge_id: str, credential_json: dict):
    row = _pop_challenge(challenge_id, "authentication")
    if not row:
        raise ValueError("Authentication challenge expired or invalid")

    credential = parse_authentication_credential_json(json.dumps(credential_json))
    cred_id_b64 = bytes_to_base64url(credential.raw_id)

    with get_db() as conn:
        pk_row = conn.execute(
            "SELECT * FROM passkeys WHERE credential_id=?", (cred_id_b64,)
        ).fetchone()
        if not pk_row:
            raise ValueError("Unknown passkey")

        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(row["challenge"]),
            expected_rp_id=rp_id(),
            expected_origin=settings.BASE_URL.rstrip("/"),
            credential_public_key=base64url_to_bytes(pk_row["public_key"]),
            credential_current_sign_count=pk_row["sign_count"],
        )

        conn.execute(
            "UPDATE passkeys SET sign_count=?, last_used_at=? WHERE id=?",
            (verification.new_sign_count, now_iso(), pk_row["id"]),
        )
        user = conn.execute(
            "SELECT id, name, role FROM users WHERE id=?", (pk_row["user_id"],)
        ).fetchone()
    return user
