from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from alq.errors import EpubValidationError


@dataclass(frozen=True, slots=True)
class EpubValidationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    epubcheck_executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "epubcheck_executed": self.epubcheck_executed,
        }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_external_uri(href: str) -> bool:
    lowered = href.strip().lower()
    return lowered.startswith(("http:", "https:", "mailto:", "data:", "tel:", "urn:"))


def _resolve_zip_path(base_dir: PurePosixPath, raw_href: str) -> str:
    without_fragment = raw_href.split(chr(35), 1)[0].split("?", 1)[0].strip()
    decoded = unquote(without_fragment)
    combined = base_dir / PurePosixPath(decoded)

    normalized_parts: list[str] = []
    for part in combined.parts:
        if part in ("", ".", "/"):
            continue
        if part == "..":
            if normalized_parts:
                normalized_parts.pop()
            continue
        normalized_parts.append(part)

    return "/".join(normalized_parts)


def _validate_xhtml_document(
    zf: zipfile.ZipFile,
    zip_path: str,
    zip_entries: set[str],
    errors: list[str],
) -> None:
    try:
        raw_bytes = zf.read(zip_path)
        root = ET.fromstring(raw_bytes.decode("utf-8"))
    except Exception as exc:
        errors.append(f"Documento XHTML/XML malformado em '{zip_path}': {exc}")
        return

    doc_dir = PurePosixPath(zip_path).parent

    for elem in root.iter():
        lname = _local_name(elem.tag)
        if lname == "img":
            src = elem.attrib.get("src", "").strip()
            if not src:
                errors.append(f"Elemento <img> sem atributo 'src' em '{zip_path}'.")
            elif not _is_external_uri(src):
                resolved_img = _resolve_zip_path(doc_dir, src)
                if resolved_img not in zip_entries:
                    errors.append(
                        f"Imagem referenciada em '{zip_path}' está ausente no ZIP: "
                        f"'{resolved_img}'."
                    )
        elif lname == "link":
            href = elem.attrib.get("href", "").strip()
            if href and not _is_external_uri(href):
                resolved_link = _resolve_zip_path(doc_dir, href)
                if resolved_link not in zip_entries:
                    errors.append(
                        f"Stylesheet/recurso referenciado em '{zip_path}' está ausente no ZIP: "
                        f"'{resolved_link}'."
                    )


def validate_epub_file(
    epub_path: Path | str,
    *,
    run_epubcheck: bool = True,
) -> EpubValidationReport:
    target_path = Path(epub_path)
    errors: list[str] = []
    warnings: list[str] = []

    if not target_path.exists():
        errors.append(f"O arquivo EPUB '{target_path}' não existe.")
        return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

    if not target_path.is_file():
        errors.append(f"O caminho '{target_path}' não é um arquivo regular.")
        return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

    try:
        file_size = target_path.stat().st_size
    except OSError as exc:
        errors.append(f"Não foi possível inspecionar o arquivo EPUB '{target_path}': {exc}")
        return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

    if file_size <= 0:
        errors.append(f"O arquivo EPUB '{target_path}' está vazio (0 bytes).")
        return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

    if not zipfile.is_zipfile(target_path):
        errors.append(f"O arquivo '{target_path}' não é um arquivo ZIP válido.")
        return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

    try:
        with zipfile.ZipFile(target_path, "r") as zf:
            zip_entries = set(zf.namelist())

            if "mimetype" not in zip_entries:
                errors.append("Arquivo obrigatório 'mimetype' ausente no pacote EPUB.")
            else:
                mimetype_val = zf.read("mimetype").decode("ascii", errors="replace").strip()
                if mimetype_val != "application/epub+zip":
                    errors.append(
                        f"Conteúdo inválido em 'mimetype': esperado 'application/epub+zip', "
                        f"encontrado '{mimetype_val}'."
                    )

            if "META-INF/container.xml" not in zip_entries:
                errors.append("Arquivo obrigatório 'META-INF/container.xml' ausente no EPUB.")
                return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

            try:
                container_raw = zf.read("META-INF/container.xml").decode("utf-8")
                container_root = ET.fromstring(container_raw)
            except Exception as exc:
                errors.append(f"XML inválido em 'META-INF/container.xml': {exc}")
                return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

            opf_paths = [
                elem.attrib.get("full-path", "").strip()
                for elem in container_root.iter()
                if _local_name(elem.tag) == "rootfile" and elem.attrib.get("full-path", "").strip()
            ]
            if not opf_paths:
                errors.append(
                    "Nenhum elemento <rootfile full-path='...'> encontrado em "
                    "'META-INF/container.xml'."
                )
                return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

            opf_path = opf_paths[0]
            if opf_path not in zip_entries:
                errors.append(
                    f"Arquivo OPF principal '{opf_path}' apontado por container.xml "
                    "não existe no pacote ZIP."
                )
                return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

            try:
                opf_raw = zf.read(opf_path).decode("utf-8")
                opf_root = ET.fromstring(opf_raw)
            except Exception as exc:
                errors.append(f"XML inválido no manifesto OPF '{opf_path}': {exc}")
                return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

            has_title = False
            has_identifier = False
            has_language = False
            manifest_items: list[tuple[str, str, str]] = []
            spine_idrefs: list[str] = []

            for elem in opf_root.iter():
                lname = _local_name(elem.tag)
                if lname == "title" and (elem.text or "").strip():
                    has_title = True
                elif lname == "identifier" and (elem.text or "").strip():
                    has_identifier = True
                elif lname == "language" and (elem.text or "").strip():
                    has_language = True
                elif lname == "item":
                    item_id = elem.attrib.get("id", "").strip()
                    item_href = elem.attrib.get("href", "").strip()
                    item_media = elem.attrib.get("media-type", "").strip()
                    if item_href:
                        manifest_items.append((item_id, item_href, item_media))
                elif lname == "itemref":
                    idref = elem.attrib.get("idref", "").strip()
                    if idref:
                        spine_idrefs.append(idref)

            if not has_identifier:
                errors.append("Metadado obrigatório 'dc:identifier' ausente ou vazio no OPF.")
            if not has_title:
                errors.append("Metadado obrigatório 'dc:title' ausente ou vazio no OPF.")
            if not has_language:
                errors.append("Metadado obrigatório 'dc:language' ausente ou vazio no OPF.")
            if not manifest_items:
                errors.append("O elemento <manifest> do OPF não contém nenhum item.")
            if not spine_idrefs:
                errors.append("O elemento <spine> do OPF não contém nenhum <itemref>.")

            opf_dir = PurePosixPath(opf_path).parent
            manifest_ids: set[str] = set()
            checked_xml_paths: set[str] = set()

            for item_id, item_href, item_media in manifest_items:
                if item_id:
                    manifest_ids.add(item_id)
                if _is_external_uri(item_href):
                    continue
                resolved_path = _resolve_zip_path(opf_dir, item_href)
                if resolved_path not in zip_entries:
                    errors.append(
                        f"Recurso declarado no <manifest> está ausente no ZIP: '{resolved_path}'."
                    )
                    continue

                is_xhtml_or_xml = item_media in (
                    "application/xhtml+xml",
                    "application/x-dtbncx+xml",
                ) or resolved_path.endswith((".xhtml", ".html", ".ncx", ".xml"))
                if is_xhtml_or_xml and resolved_path not in checked_xml_paths:
                    checked_xml_paths.add(resolved_path)
                    _validate_xhtml_document(zf, resolved_path, zip_entries, errors)

            for idref in spine_idrefs:
                if idref not in manifest_ids:
                    errors.append(
                        f"O <itemref idref='{idref}'> do <spine> não corresponde "
                        "a nenhum item do <manifest>."
                    )

            for entry_name in sorted(zip_entries):
                if (
                    entry_name.endswith((".xhtml", ".html", ".ncx"))
                    and entry_name not in checked_xml_paths
                ):
                    checked_xml_paths.add(entry_name)
                    _validate_xhtml_document(zf, entry_name, zip_entries, errors)
    except zipfile.BadZipFile as exc:
        errors.append(f"Falha ao ler estrutura ZIP do arquivo EPUB '{target_path}': {exc}")
        return EpubValidationReport(valid=False, errors=errors, warnings=warnings)

    epubcheck_executed = False
    if run_epubcheck and not errors:
        epubcheck_bin = shutil.which("epubcheck")
        if epubcheck_bin is not None:
            epubcheck_executed = True
            proc = subprocess.run(
                [epubcheck_bin, str(target_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                errors.append(
                    f"EPUBCheck reportou falha de conformidade (código {proc.returncode}): {detail}"
                )

    return EpubValidationReport(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        epubcheck_executed=epubcheck_executed,
    )


def ensure_valid_epub(
    epub_path: Path | str,
    *,
    run_epubcheck: bool = True,
) -> EpubValidationReport:
    report = validate_epub_file(epub_path, run_epubcheck=run_epubcheck)
    if not report.valid:
        joined_errors = " ".join(report.errors)
        raise EpubValidationError(
            f"O arquivo EPUB gerado '{epub_path}' falhou na validação estrutural: {joined_errors}",
            warnings=report.warnings,
        )
    return report


__all__ = [
    "EpubValidationReport",
    "ensure_valid_epub",
    "validate_epub_file",
]
