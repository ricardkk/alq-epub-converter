from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Metadata:
    title: str | None = None
    author: str | None = None
    language: str = "und"
    identifier: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "author": self.author,
            "language": self.language,
            "identifier": self.identifier,
        }


__all__ = ["Metadata"]
