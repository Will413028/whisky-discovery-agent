"""Auth0 access-token adapter. Token claims never select the JWKS endpoint."""

from dataclasses import dataclass

import jwt


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str


@dataclass(frozen=True)
class VerifiedAccess:
    principal: Principal
    expires_at: float


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, jwks_url: str) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_url = jwks_url
        self.keys = jwt.PyJWKClient(jwks_url, timeout=5, lifespan=300)

    def verify_access(self, token: str) -> VerifiedAccess:
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
            if not claims["sub"].strip():
                raise InvalidToken
            return VerifiedAccess(
                Principal(claims["iss"], claims["sub"]), float(claims["exp"])
            )
        except jwt.PyJWTError:
            raise InvalidToken from None

    def verify(self, token: str) -> Principal:
        return self.verify_access(token).principal
