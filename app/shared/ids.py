try:
    from uuid6 import uuid7

    def new_id() -> str:
        return str(uuid7())

except ImportError:
    import uuid

    def new_id() -> str:
        return str(uuid.uuid4())
