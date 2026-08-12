import uuid

ID_MAX_LENGTH = 40


def new_id(prefix: str) -> str:
    suffix_length = ID_MAX_LENGTH - len(prefix) - 1
    if suffix_length < 16:
        raise ValueError("id_prefix_too_long")
    return f"{prefix}_{uuid.uuid4().hex[:suffix_length]}"
