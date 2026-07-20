import jwt
from django.conf import settings

# Shared by accounts/services.py (signing) and accounts/authentication.py
# (verifying) so the algorithm can't drift between the two call sites.
ALGORITHM = "HS256"


def encode(payload):
    return jwt.encode(payload, settings.ACCESS_TOKEN_SECRET, algorithm=ALGORITHM)


def decode(token):
    # Let jwt.ExpiredSignatureError / jwt.InvalidTokenError propagate —
    # callers already handle those specifically.
    return jwt.decode(token, settings.ACCESS_TOKEN_SECRET, algorithms=[ALGORITHM])
