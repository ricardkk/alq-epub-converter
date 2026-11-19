from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str

    @property
    def type(self) -> Literal["paragraph"]:
        return "paragraph"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class Heading:
    text: str
    level: int = 1

    @property
    def type(self) -> Literal["heading"]:
        return "heading"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
            "level": self.level,
        }


@dataclass(frozen=True, slots=True)
class ImageBlock:
    asset_id: str
    alt_text: str | None = None

    @property
    def type(self) -> Literal["image"]:
        return "image"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "asset_id": self.asset_id,
            "alt_text": self.alt_text,
        }


@dataclass(frozen=True, slots=True)
class ListBlock:
    ordered: bool
    items: list[str]

    @property
    def type(self) -> Literal["list"]:
        return "list"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "ordered": self.ordered,
            "items": list(self.items),
        }


Block = Paragraph | Heading | ImageBlock | ListBlock

__all__ = [
    "Block",
    "Heading",
    "ImageBlock",
    "ListBlock",
    "Paragraph",
]
