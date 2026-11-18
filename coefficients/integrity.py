from hashlib import sha256


class BlockDataError(ValueError):
    pass


def is_digest(text):
    return (
        type(text) is str and len(text) == 64
        and all(character in '0123456789abcdef' for character in text)
    )


def payload_digest(payload):
    return sha256(payload).hexdigest()


def verify_payload(payload, expected_digest):
    if type(payload) is not bytes or payload_digest(payload) != expected_digest:
        raise BlockDataError('original block payload digest does not match')
