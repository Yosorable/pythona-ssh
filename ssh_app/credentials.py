"""Local credential encryption with a fixed application key."""

import json


# This protects stored text from casual inspection, not from someone with the source.
APPLICATION_KEY = b"OTbVToK6La5DFgF0yUa_R5wAdlG4P4X7G8IAwHzTWwI="


def encrypt(value):
    from cryptography.fernet import Fernet
    return Fernet(APPLICATION_KEY).encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8")).decode("ascii")


def decrypt(token):
    from cryptography.fernet import Fernet, InvalidToken
    try:
        return json.loads(Fernet(APPLICATION_KEY).decrypt(token.encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, UnicodeError) as error:
        raise ValueError("credentials_unreadable") from error
