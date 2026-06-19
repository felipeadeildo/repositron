"""The partial-update sentinel.

One canonical singleton, compared by identity. A field equal to `UNSET` on an
update payload is skipped (left untouched); `None` is a real value (SET NULL).
"""

from typing import Final


class UnsetType:
    """Type of the `UNSET` sentinel; instances compare equal only by identity.

    Annotate an optional update field as `int | UnsetType = UNSET` so it can be
    distinguished from an explicit `None`.
    """

    _instance: "UnsetType | None" = None

    def __new__(cls) -> "UnsetType":
        # ponytail: enforce the singleton so identity comparison is always safe,
        # even if someone calls UnsetType() directly.
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Final[UnsetType] = UnsetType()
