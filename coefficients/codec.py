def encode_integers(values):
    encoded = bytearray()
    for value in values:
        if type(value) is not int:
            raise ValueError('coefficient payloads require integers')
        # Zigzag maps signed values to unsigned varints without a machine word limit.
        unsigned = 2 * value if value >= 0 else -2 * value - 1
        while unsigned >= 128:
            encoded.append((unsigned & 127) | 128)
            unsigned >>= 7
        encoded.append(unsigned)
    return bytes(encoded)


def decode_integers(payload, count):
    if type(payload) is not bytes or type(count) is not int or count < 0:
        raise ValueError('expected payload bytes and a nonnegative element count')
    values = []
    unsigned = 0
    shift = 0
    for octet in payload:
        if len(values) == count:
            raise ValueError('coefficient payload has extra bytes')
        unsigned |= (octet & 127) << shift
        if octet & 128:
            shift += 7
            continue
        if shift and octet == 0:
            raise ValueError('noncanonical integer encoding')
        value = unsigned >> 1
        values.append(-value - 1 if unsigned & 1 else value)
        unsigned = 0
        shift = 0
    if shift or len(values) != count:
        raise ValueError('coefficient payload is truncated or has the wrong element count')
    return tuple(values)
