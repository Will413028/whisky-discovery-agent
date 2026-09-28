import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from whisky.modules.identity.tokens import InvalidToken, Principal

ISSUER = "https://whisky-fixture.example/"


def test_valid_signed_access_token_resolves_principal(signed_tokens):
    verifier, sign = signed_tokens
    assert verifier.verify(sign()) == Principal(ISSUER, "auth0|fixture")


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://wrong.example/"},
        {"aud": "wrong-api"},
        {"exp": 1},
        {"iat": 9999999999},
        {"nbf": 9999999999},
        {"sub": 123},
        {"exp": None},
        {"iat": None},
    ],
)
def test_library_rejects_invalid_claims(signed_tokens, changes):
    verifier, sign = signed_tokens
    with pytest.raises(InvalidToken):
        verifier.verify(sign(**changes))


def test_rejects_wrong_signature(signed_tokens):
    verifier, sign = signed_tokens
    token = sign()
    claims = jwt.decode(token, options={"verify_signature": False})
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong = jwt.encode(
        claims, other_key, algorithm="RS256", headers={"kid": "whisky-fixture"}
    )
    with pytest.raises(InvalidToken):
        verifier.verify(wrong)


def test_rejects_empty_subject(signed_tokens):
    verifier, sign = signed_tokens
    with pytest.raises(InvalidToken):
        verifier.verify(sign(sub=""))
