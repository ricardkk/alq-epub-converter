from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from alq.domain.blocks import Block, Heading, ImageBlock, Paragraph
from alq.domain.metadata import Metadata


@dataclass(frozen=True, slots=True)
class ImageAsset:
    asset_id: str
    media_type: str
    data: bytes
    filename: str
    width: int = 0
    height: int = 0
    page_number: int = 1

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "media_type": self.media_type,
            "filename": self.filename,
            "width": self.width,
            "height": self.height,
            "page_number": self.page_number,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class Chapter:
    title: str | None
    level: int = 1
    blocks: list[Block] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "level": self.level,
            "blocks": [block.to_dict() for block in self.blocks],
        }


@dataclass(frozen=True, slots=True)
class Document:
    metadata: Metadata
    chapters: list[Chapter] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assets: dict[str, ImageAsset] = field(default_factory=dict)

    @property
    def paragraph_count(self) -> int:
        return sum(
            1
            for chapter in self.chapters
            for block in chapter.blocks
            if isinstance(block, Paragraph)
        )

    @property
    def heading_count(self) -> int:
        return sum(
            1 for chapter in self.chapters for block in chapter.blocks if isinstance(block, Heading)
        )

    @property
    def image_count(self) -> int:
        block_images = sum(
            1
            for chapter in self.chapters
            for block in chapter.blocks
            if isinstance(block, ImageBlock)
        )
        return max(len(self.assets), block_images)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "chapters": [chapter.to_dict() for chapter in self.chapters],
            "warnings": list(self.warnings),
            "assets": {asset_id: asset.to_dict() for asset_id, asset in self.assets.items()},
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


__all__ = [
    "Chapter",
    "Document",
    "ImageAsset",
]
