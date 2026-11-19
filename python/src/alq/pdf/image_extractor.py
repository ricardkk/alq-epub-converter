from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from alq.domain.document import ImageAsset
from alq.pdf.reader import open_pdf
from alq.pdf.text_extractor import BoundingBox
from alq.protocol import emit_debug

_DIRECT_EPUB_IMAGE_FORMATS: dict[str, tuple[str, str]] = {
    "png": ("image/png", "png"),
    "jpg": ("image/jpeg", "jpg"),
    "jpeg": ("image/jpeg", "jpg"),
    "gif": ("image/gif", "gif"),
    "webp": ("image/webp", "webp"),
}

DEFAULT_MIN_IMAGE_WIDTH: int = 32
DEFAULT_MIN_IMAGE_HEIGHT: int = 32
DEFAULT_MIN_IMAGE_AREA: int = 1600
_MIN_RENDERED_RECT_SIDE_PT: float = 12.0


@dataclass(frozen=True, slots=True)
class ExtractedImagePlacement:
    asset_id: str
    page_number: int
    bbox: BoundingBox
    alt_text: str | None = None
    column_index: int = 0

    @property
    def kind(self) -> Literal["image"]:
        return "image"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "asset_id": self.asset_id,
            "page_number": self.page_number,
            "bbox": self.bbox.to_dict(),
            "alt_text": self.alt_text,
            "column_index": self.column_index,
        }


@dataclass(frozen=True, slots=True)
class ImageExtractionResult:
    assets: dict[str, ImageAsset] = field(default_factory=dict)
    placements_by_page: dict[int, list[ExtractedImagePlacement]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_placements(self) -> list[ExtractedImagePlacement]:
        return [
            placement
            for page_num in sorted(self.placements_by_page.keys())
            for placement in self.placements_by_page[page_num]
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "assets": {asset_id: asset.to_dict() for asset_id, asset in self.assets.items()},
            "placements": [placement.to_dict() for placement in self.all_placements],
            "warnings": list(self.warnings),
        }


def normalize_image_bytes(
    raw_bytes: bytes,
    raw_ext: str = "png",
) -> tuple[bytes, str, str, int, int]:
    if not raw_bytes:
        raise ValueError("bytes de imagem vazios")

    ext_clean = raw_ext.strip().lower().lstrip(".")
    with Image.open(io.BytesIO(raw_bytes)) as pil_img:
        pil_img.load()
        width, height = pil_img.size
        mode = pil_img.mode

        if ext_clean in _DIRECT_EPUB_IMAGE_FORMATS and mode in ("RGB", "RGBA", "L", "P"):
            media_type, norm_ext = _DIRECT_EPUB_IMAGE_FORMATS[ext_clean]
            return (raw_bytes, media_type, norm_ext, int(width), int(height))

        if mode in ("RGBA", "LA") or (mode == "P" and "transparency" in pil_img.info):
            converted = pil_img.convert("RGBA")
        elif mode == "L":
            converted = pil_img
        else:
            converted = pil_img.convert("RGB")

        out_buf = io.BytesIO()
        converted.save(out_buf, format="PNG")
        return (out_buf.getvalue(), "image/png", "png", int(width), int(height))


def _extract_raw_image_dict(doc: Any, xref: int) -> Mapping[str, Any] | None:
    raw = doc.extract_image(xref)
    if isinstance(raw, Mapping) and raw.get("image"):
        return raw
    return None


def extract_pdf_images(
    path: Path | str,
    *,
    min_width: int = DEFAULT_MIN_IMAGE_WIDTH,
    min_height: int = DEFAULT_MIN_IMAGE_HEIGHT,
    min_area: int = DEFAULT_MIN_IMAGE_AREA,
    debug: bool = False,
) -> ImageExtractionResult:
    pdf_path = Path(path)
    assets: dict[str, ImageAsset] = {}
    placements_by_page: dict[int, list[ExtractedImagePlacement]] = {}
    warnings: list[str] = []

    xref_to_asset_id: dict[int, str] = {}
    ignored_xrefs: set[int] = set()
    failed_xrefs: set[int] = set()
    next_index = 1

    with open_pdf(pdf_path) as doc:
        page_count = int(doc.page_count)
        for page_idx in range(page_count):
            page_number = page_idx + 1
            try:
                page = doc.load_page(page_idx)
                page_width = round(float(page.rect.width), 2)
                image_list = page.get_images(full=True)
            except Exception as exc:
                warnings.append(f"Não foi possível listar imagens da página {page_number}: {exc}")
                continue

            seen_on_page: set[tuple[int, float, float, float, float]] = set()
            page_placements: list[ExtractedImagePlacement] = []

            for img_entry in image_list:
                if not img_entry:
                    continue
                xref = int(img_entry[0])
                if xref <= 0 or xref in ignored_xrefs or xref in failed_xrefs:
                    continue

                if xref not in xref_to_asset_id:
                    try:
                        raw_dict = _extract_raw_image_dict(doc, xref)
                        if raw_dict is None:
                            failed_xrefs.add(xref)
                            warnings.append(
                                f"Imagem incorporada (xref={xref}) na página {page_number} "
                                "não contém stream binário extraível."
                            )
                            continue

                        raw_bytes = bytes(raw_dict["image"])
                        raw_ext = str(raw_dict.get("ext", "png") or "png")
                        norm_bytes, media_type, norm_ext, width, height = normalize_image_bytes(
                            raw_bytes,
                            raw_ext,
                        )
                    except Exception as exc:
                        failed_xrefs.add(xref)
                        warnings.append(
                            f"Falha ao extrair ou converter imagem (xref={xref}) "
                            f"na página {page_number}: {exc}"
                        )
                        continue

                    if width < min_width or height < min_height or (width * height) < min_area:
                        ignored_xrefs.add(xref)
                        emit_debug(
                            f"Imagem pequena/decorativa ignorada: xref={xref} "
                            f"({width}x{height}) na página {page_number}",
                            enabled=debug,
                        )
                        continue

                    asset_id = f"img_{next_index:03d}"
                    next_index += 1
                    filename = f"images/{asset_id}.{norm_ext}"
                    asset = ImageAsset(
                        asset_id=asset_id,
                        media_type=media_type,
                        data=norm_bytes,
                        filename=filename,
                        width=width,
                        height=height,
                        page_number=page_number,
                    )
                    assets[asset_id] = asset
                    xref_to_asset_id[xref] = asset_id

                asset_id = xref_to_asset_id[xref]
                asset = assets[asset_id]

                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    rects = []

                candidate_boxes: list[BoundingBox] = []
                for rect in rects:
                    if rect.is_empty or rect.is_infinite:
                        continue
                    box = BoundingBox(
                        x0=round(float(rect.x0), 2),
                        y0=round(float(rect.y0), 2),
                        x1=round(float(rect.x1), 2),
                        y1=round(float(rect.y1), 2),
                    )
                    if (
                        box.width < _MIN_RENDERED_RECT_SIDE_PT
                        or box.height < _MIN_RENDERED_RECT_SIDE_PT
                    ):
                        continue
                    candidate_boxes.append(box)

                if not candidate_boxes and not rects:
                    candidate_boxes.append(
                        BoundingBox(
                            x0=0.0,
                            y0=0.0,
                            x1=round(float(asset.width), 2),
                            y1=round(float(asset.height), 2),
                        )
                    )

                mid_x = page_width / 2.0 if page_width > 0.0 else 297.5
                gutter_tol = page_width * 0.04 if page_width > 0.0 else 20.0
                max_col_w = page_width * 0.56 if page_width > 0.0 else 330.0

                for box in candidate_boxes:
                    dedup_key = (xref, box.x0, box.y0, box.x1, box.y1)
                    if dedup_key in seen_on_page:
                        continue
                    seen_on_page.add(dedup_key)

                    col_idx = (
                        1
                        if (
                            box.width <= max_col_w
                            and box.x0 >= mid_x - gutter_tol
                            and box.center_x > mid_x
                        )
                        else 0
                    )
                    page_placements.append(
                        ExtractedImagePlacement(
                            asset_id=asset_id,
                            page_number=page_number,
                            bbox=box,
                            alt_text=f"Imagem da página {page_number}",
                            column_index=col_idx,
                        )
                    )

            if page_placements:
                page_placements.sort(
                    key=lambda p: (
                        p.column_index,
                        round(p.bbox.y0, 2),
                        round(p.bbox.x0, 2),
                        p.asset_id,
                    )
                )
                placements_by_page[page_number] = page_placements

    emit_debug(
        f"Extração de imagens concluída para '{pdf_path}': "
        f"assets={len(assets)}, warnings={len(warnings)}",
        enabled=debug,
    )

    return ImageExtractionResult(
        assets=assets,
        placements_by_page=placements_by_page,
        warnings=warnings,
    )


__all__ = [
    "DEFAULT_MIN_IMAGE_AREA",
    "DEFAULT_MIN_IMAGE_HEIGHT",
    "DEFAULT_MIN_IMAGE_WIDTH",
    "ExtractedImagePlacement",
    "ImageExtractionResult",
    "extract_pdf_images",
    "normalize_image_bytes",
]
