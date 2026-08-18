"""Detect and fill Amazon blank NOC templates.

Two templates are supported:

1) Maharashtra FC AcroForm (BOM-style): CurrentDate, SellerName, AddressLine1/2.
   Incremental save keeps Amazon’s PKCS#7 bytes; status is often MODIFIED.

2) Generic NAX-1 blank (Print-to-PDF / dotted placeholders, no widgets):
   Overlay Date, Branch, FC address, State, M/S, M/s., merchant address,
   then verify. If this copy has no PKCS#7 (common after Print to PDF),
   verification correctly reports UNSIGNED.

Amazon BOM behaviour is unchanged.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import fitz

FIELD_DATE = "CurrentDate"
FIELD_SELLER = "SellerName"
FIELD_ADDR1 = "AddressLine1"
FIELD_ADDR2 = "AddressLine2"
FIELD_SIGNATURE = "Signature1"

NAX_META_FLAG = "PDF-Sign-Verifier-NAX-FILLED"
DOTTED_PLACEHOLDER_RE = re.compile(r"^[\s.….\-_]+$")


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    if not text or DOTTED_PLACEHOLDER_RE.match(text):
        return ""
    return text


@dataclass
class NocFieldSnapshot:
    name: str
    label: str
    value: str
    filled: bool
    widget_count: int = 1
    editable: bool = True
    required: bool = True
    multiline: bool = False


@dataclass
class NocFormStatus:
    """Fillable Amazon NOC status for the UI."""

    is_amazon_noc: bool
    needs_fill: bool
    complete: bool
    fields: list[NocFieldSnapshot] = field(default_factory=list)
    message: str = ""
    template: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_amazon_noc": self.is_amazon_noc,
            "needs_fill": self.needs_fill,
            "complete": self.complete,
            "message": self.message,
            "template": self.template,
            "fields": [asdict(f) for f in self.fields],
            "values": {f.name: f.value for f in self.fields},
        }


def _field_value_from_widget(doc: fitz.Document, widget: fitz.Widget) -> str:
    """Resolve text value, including parent field /V for multi-widget names."""
    direct = _clean(widget.field_value)
    if direct:
        return direct
    try:
        obj = doc.xref_object(widget.xref)
        if "/Parent" in obj:
            m = re.search(r"/Parent\s+(\d+)\s+0\s+R", obj)
            if m:
                parent = int(m.group(1))
                parent_obj = doc.xref_object(parent)
                vm = re.search(r"/V\s*\((.*?)\)", parent_obj, re.DOTALL)
                if vm:
                    return _clean(vm.group(1).replace("\\)", ")").replace("\\(", "("))
                try:
                    raw = doc.xref_get_key(parent, "V")
                    if raw and raw[0] == "string":
                        return _clean(raw[1])
                except Exception:
                    pass
    except Exception:
        pass
    return ""


def _collect_text_values(doc: fitz.Document) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for page in doc:
        for widget in page.widgets() or []:
            if widget.field_type_string != "Text":
                continue
            name = widget.field_name or ""
            if not name:
                continue
            values.setdefault(name, []).append(_field_value_from_widget(doc, widget))
    return values


def _page_text(doc: fitz.Document) -> str:
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text") or "")
    return "\n".join(parts)


def _is_nax_template_text(text: str) -> bool:
    t = text.replace("\n", " ")
    return (
        "Amazon Seller Services" in t
        and "No Objection" in t
        and "in the state of" in t
        and "Branch," in t
        and "M/S" in t
        and "M/s." in t
        and "fulfilment centre" in t
    )


def _nax_saved_values(doc: fitz.Document) -> dict[str, str]:
    meta = doc.metadata or {}
    blob = (meta.get("keywords") or "") + " " + (meta.get("subject") or "")
    if NAX_META_FLAG not in blob:
        return {}
    subject = meta.get("subject") or ""
    try:
        data = json.loads(subject)
        if isinstance(data, dict):
            return {str(k): _clean(str(v) if v is not None else "") for k, v in data.items()}
    except Exception:
        return {}
    return {}


def _nax_fields_from_values(values: dict[str, str]) -> list[NocFieldSnapshot]:
    specs = [
        ("date", "Date", False),
        ("branch", "Tax Officer Branch", False),
        ("fc_address", "Amazon FC / premises address", True),
        ("state", "State", False),
        ("ms_name", "M/S (Merchant name)", False),
        ("ms_name_2", "M/s. (Merchant name)", False),
        ("address", "Main place of business (address line 1)", True),
        ("address_line2", "Address line 2 (optional)", False),
    ]
    fields: list[NocFieldSnapshot] = []
    for name, label, multiline in specs:
        val = _clean(values.get(name, ""))
        required = name != "address_line2"
        if name == "ms_name_2" and not val:
            val = _clean(values.get("ms_name", ""))
        fields.append(
            NocFieldSnapshot(
                name=name,
                label=label,
                value=val,
                filled=bool(val),
                required=required,
                multiline=multiline,
            )
        )
    return fields


def _inspect_nax(doc: fitz.Document) -> NocFormStatus | None:
    text = _page_text(doc)
    saved = _nax_saved_values(doc)
    if not saved and not _is_nax_template_text(text):
        return None

    values = saved
    fields = _nax_fields_from_values(values)
    required_ok = all(f.filled for f in fields if f.required)
    if required_ok:
        msg = (
            "NAX NOC details are filled. Fields are locked; "
            "running digital signature verification."
        )
    else:
        msg = (
            "Amazon NAX blank NOC detected. Enter Date, Branch, FC address, State, "
            "M/S, M/s., and merchant address, then Fill & Verify."
        )
    return NocFormStatus(
        is_amazon_noc=True,
        needs_fill=not required_ok,
        complete=required_ok,
        fields=fields,
        message=msg,
        template="amazon_nax",
    )


def inspect_noc_form(path: str | Path) -> NocFormStatus:
    """Inspect a PDF for Amazon blank-NOC fields (BOM AcroForm or NAX overlay)."""
    path = Path(path)
    try:
        doc = fitz.open(path)
    except Exception:
        return NocFormStatus(
            is_amazon_noc=False,
            needs_fill=False,
            complete=False,
            message="Could not open PDF form fields.",
        )

    try:
        values = _collect_text_values(doc)
        has_sig = False
        for page in doc:
            for widget in page.widgets() or []:
                if widget.field_type_string == "Signature" or (
                    widget.field_name or ""
                ) == FIELD_SIGNATURE:
                    has_sig = True
                    break
            if has_sig:
                break

        has_core = (
            FIELD_DATE in values
            and FIELD_SELLER in values
            and FIELD_ADDR1 in values
        )
        is_amazon = has_core and (has_sig or FIELD_ADDR2 in values)
        if is_amazon:
            date_vals = values.get(FIELD_DATE, [""])
            seller_vals = values.get(FIELD_SELLER, [""])
            addr1_vals = values.get(FIELD_ADDR1, [""])
            addr2_vals = values.get(FIELD_ADDR2, [""])

            seller = next((v for v in seller_vals if v), "")
            date_v = next((v for v in date_vals if v), "")
            addr1_v = next((v for v in addr1_vals if v), "")
            addr2_v = next((v for v in addr2_vals if v), "")

            fields = [
                NocFieldSnapshot(
                    name="date",
                    label="Date",
                    value=date_v,
                    filled=bool(date_v),
                ),
                NocFieldSnapshot(
                    name="ms_name",
                    label="M/S (Merchant name)",
                    value=seller,
                    filled=bool(seller),
                    widget_count=len(seller_vals),
                ),
                NocFieldSnapshot(
                    name="ms_name_2",
                    label="M/s. (Merchant name)",
                    value=seller,
                    filled=bool(seller),
                    widget_count=1,
                ),
                NocFieldSnapshot(
                    name="address",
                    label="Main place of business in Maharashtra",
                    value=addr1_v,
                    filled=bool(addr1_v),
                    multiline=True,
                ),
                NocFieldSnapshot(
                    name="address_line2",
                    label="Address line 2 (optional)",
                    value=addr2_v,
                    filled=bool(addr2_v),
                    required=False,
                ),
            ]

            required_ok = bool(date_v and seller and addr1_v)
            if required_ok:
                msg = (
                    "All merchant details are already filled. Fields are locked; "
                    "verifying the digital signature."
                )
            else:
                msg = (
                    "Amazon blank NOC detected. Enter Date, M/S, M/s., and address, "
                    "then Fill & Verify."
                )
            return NocFormStatus(
                is_amazon_noc=True,
                needs_fill=not required_ok,
                complete=required_ok,
                fields=fields,
                message=msg,
                template="amazon_bom",
            )

        nax = _inspect_nax(doc)
        if nax:
            return nax

        return NocFormStatus(
            is_amazon_noc=False,
            needs_fill=False,
            complete=False,
            message="",
        )
    finally:
        doc.close()


def _set_text_field(doc: fitz.Document, widget: fitz.Widget, value: str) -> None:
    """Write a text widget value (updates parent /V when kids share a name)."""
    widget.field_value = value
    widget.update()
    try:
        obj = doc.xref_object(widget.xref)
        m = re.search(r"/Parent\s+(\d+)\s+0\s+R", obj)
        if m:
            parent = int(m.group(1))
            escaped = (
                value.replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )
            doc.xref_set_key(parent, "V", f"({escaped})")
    except Exception:
        pass


def _union_rects(rects: list[fitz.Rect]) -> fitz.Rect | None:
    if not rects:
        return None
    return fitz.Rect(
        min(r.x0 for r in rects),
        min(r.y0 for r in rects),
        max(r.x1 for r in rects),
        max(r.y1 for r in rects),
    )


def _dot_bands(page: fitz.Page) -> list[fitz.Rect]:
    hits = page.search_for("……") or []
    groups: dict[int, list[fitz.Rect]] = {}
    for rect in hits:
        groups.setdefault(int(round(rect.y0)), []).append(rect)
    bands: list[fitz.Rect] = []
    for y in sorted(groups):
        union = _union_rects(groups[y])
        if union:
            bands.append(union)
    return bands


def _split_two_lines(text: str, max_chars: int = 92) -> tuple[str, str]:
    text = _clean(text)
    if len(text) <= max_chars:
        return text, ""
    cut = text.rfind(",", 0, max_chars)
    if cut < 32:
        cut = text.rfind(" ", 0, max_chars)
    if cut < 32:
        cut = max_chars
    return text[:cut].strip(" ,"), text[cut:].strip(" ,")


def _fit_fontsize(text: str, width: float, *, max_size: float = 9.0, min_size: float = 6.5) -> float:
    """Pick a font size that fits approximate band width (helv)."""
    n = max(len(text), 1)
    size = min(max_size, max(min_size, width / (n * 0.48)))
    return round(size, 1)


def _write_line(page: fitz.Page, rect: fitz.Rect, text: str, *, fontsize: float = 8.0) -> None:
    if not text:
        return
    pad = fitz.Rect(rect.x0 - 1, rect.y0 - 1.2, rect.x1 + 2, rect.y1 + 1.2)
    page.draw_rect(pad, color=(1, 1, 1), fill=(1, 1, 1), width=0, overlay=True)
    fs = _fit_fontsize(text, pad.width, max_size=fontsize)
    # insert_textbox often fails on narrow dotted bands — prefer insert_text.
    y = pad.y0 + fs * 0.85
    page.insert_text(
        fitz.Point(pad.x0 + 1, y),
        text,
        fontname="helv",
        fontsize=fs,
        color=(0, 0, 0),
        overlay=True,
    )


def _write_wrapped(page: fitz.Page, rect: fitz.Rect, text: str, *, fontsize: float = 7.8) -> None:
    """Write longer text into a wide band using textbox with smaller font."""
    if not text:
        return
    pad = fitz.Rect(rect.x0 - 1, rect.y0 - 1.2, rect.x1 + 2, rect.y1 + 1.2)
    page.draw_rect(pad, color=(1, 1, 1), fill=(1, 1, 1), width=0, overlay=True)
    fs = min(fontsize, _fit_fontsize(text, pad.width, max_size=fontsize))
    rc = page.insert_textbox(
        pad,
        text,
        fontname="helv",
        fontsize=fs,
        color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_LEFT,
        overlay=True,
    )
    if rc < 0:
        page.insert_text(
            fitz.Point(pad.x0 + 1, pad.y0 + fs * 0.9),
            text[:120],
            fontname="helv",
            fontsize=fs,
            color=(0, 0, 0),
            overlay=True,
        )


def _fill_nax_overlay(
    source_pdf: Path,
    output_pdf: Path,
    values: dict[str, str],
) -> NocFormStatus:
    date_v = _clean(values.get("date"))
    branch = _clean(values.get("branch"))
    fc_address = _clean(values.get("fc_address"))
    state = _clean(values.get("state"))
    name1 = _clean(values.get("ms_name"))
    name2 = _clean(values.get("ms_name_2")) or name1
    addr1 = _clean(values.get("address"))
    addr2 = _clean(values.get("address_line2"))

    missing = []
    if not date_v:
        missing.append("Date")
    if not branch:
        missing.append("Branch")
    if not fc_address:
        missing.append("FC / premises address")
    if not state:
        missing.append("State")
    if not name1:
        missing.append("M/S")
    if not addr1:
        missing.append("Merchant address")
    if missing:
        raise ValueError("Required fields missing: " + ", ".join(missing))

    if source_pdf.resolve() != output_pdf.resolve():
        shutil.copy2(source_pdf, output_pdf)

    stored = {
        "date": date_v,
        "branch": branch,
        "fc_address": fc_address,
        "state": state,
        "ms_name": name1,
        "ms_name_2": name2,
        "address": addr1,
        "address_line2": addr2,
    }

    doc = fitz.open(output_pdf)
    try:
        page = doc[0]
        bands = _dot_bands(page)
        if len(bands) < 8:
            raise ValueError("Could not locate NAX dotted fields on this PDF.")

        by_y = {int(round(b.y0)): b for b in bands}

        def band_near(*targets: int) -> fitz.Rect | None:
            for t in targets:
                if t in by_y:
                    return by_y[t]
                for key, rect in by_y.items():
                    if abs(key - t) <= 2:
                        return rect
            return None

        date_r = band_near(85)
        branch_r = band_near(110)
        fc1_r = band_near(189)
        fc2_r = band_near(211)
        state_prem_r = band_near(232)
        ms_r = band_near(268)
        state_fc_r = band_near(305)
        ms2_r = band_near(356)
        state_biz_r = band_near(387)
        addr1_r = band_near(400)
        addr2_r = band_near(417)
        state_conf_r = band_near(614)

        fc_l1, fc_l2 = _split_two_lines(fc_address)
        merch_l1, merch_l2 = addr1, addr2
        if not merch_l2:
            merch_l1, merch_l2 = _split_two_lines(addr1)

        if date_r:
            _write_line(page, date_r, date_v, fontsize=8.0)
        if branch_r:
            _write_line(page, branch_r, branch, fontsize=8.0)
        if fc1_r:
            _write_wrapped(page, fc1_r, fc_l1)
        if fc2_r:
            _write_wrapped(page, fc2_r, fc_l2 or "")
        if state_prem_r:
            _write_line(page, state_prem_r, state, fontsize=8.0)
        if ms_r:
            _write_wrapped(page, ms_r, name1)
        if state_fc_r:
            _write_line(page, state_fc_r, state, fontsize=8.0)
        if ms2_r:
            _write_wrapped(page, ms2_r, name2)
        if state_biz_r:
            _write_line(page, state_biz_r, state, fontsize=8.0)
        if addr1_r:
            _write_wrapped(page, addr1_r, merch_l1)
        if addr2_r:
            _write_wrapped(page, addr2_r, merch_l2)
        if state_conf_r:
            _write_line(page, state_conf_r, state, fontsize=8.0)

        meta = dict(doc.metadata or {})
        meta["keywords"] = NAX_META_FLAG
        meta["subject"] = json.dumps(stored, ensure_ascii=False)
        doc.set_metadata(meta)

        try:
            doc.saveIncr()
        except Exception:
            tmp = output_pdf.with_suffix(".tmp.pdf")
            doc.save(tmp, garbage=0, deflate=True)
            doc.close()
            tmp.replace(output_pdf)
            return inspect_noc_form(output_pdf)
    finally:
        if not doc.is_closed:
            doc.close()

    return inspect_noc_form(output_pdf)


def fill_noc_form(
    source_pdf: str | Path,
    output_pdf: str | Path,
    *,
    date: str,
    ms_name: str,
    ms_name_2: str | None = None,
    address: str,
    address_line2: str = "",
    branch: str = "",
    state: str = "",
    fc_address: str = "",
) -> NocFormStatus:
    """Write merchant details into Amazon NOC fields, then return form status."""
    source_pdf = Path(source_pdf)
    output_pdf = Path(output_pdf)
    status = inspect_noc_form(source_pdf)
    if status.template == "amazon_nax":
        return _fill_nax_overlay(
            source_pdf,
            output_pdf,
            {
                "date": date,
                "branch": branch,
                "state": state,
                "fc_address": fc_address,
                "ms_name": ms_name,
                "ms_name_2": ms_name_2 or ms_name,
                "address": address,
                "address_line2": address_line2,
            },
        )

    date_v = _clean(date)
    name1 = _clean(ms_name)
    name2 = _clean(ms_name_2) if ms_name_2 is not None else name1
    seller = name1 or name2
    addr1 = _clean(address)
    addr2 = _clean(address_line2)

    missing = []
    if not date_v:
        missing.append("Date")
    if not seller:
        missing.append("M/S")
    if not addr1:
        missing.append("Address")
    if missing:
        raise ValueError("Required fields missing: " + ", ".join(missing))

    if source_pdf.resolve() != output_pdf.resolve():
        shutil.copy2(source_pdf, output_pdf)

    doc = fitz.open(output_pdf)
    try:
        seller_done = False
        updated = 0
        for page in doc:
            for widget in page.widgets() or []:
                if widget.field_type_string != "Text":
                    continue
                name = widget.field_name or ""
                if name == FIELD_DATE:
                    _set_text_field(doc, widget, date_v)
                    updated += 1
                elif name == FIELD_SELLER:
                    _set_text_field(doc, widget, seller)
                    seller_done = True
                    updated += 1
                elif name == FIELD_ADDR1:
                    _set_text_field(doc, widget, addr1)
                    updated += 1
                elif name == FIELD_ADDR2:
                    _set_text_field(doc, widget, addr2)
                    updated += 1

        if updated == 0 or not seller_done:
            raise ValueError("No Amazon NOC form fields found to fill.")

        try:
            doc.saveIncr()
        except Exception:
            tmp = output_pdf.with_suffix(".tmp.pdf")
            doc.save(tmp, garbage=0, deflate=True)
            doc.close()
            tmp.replace(output_pdf)
            return inspect_noc_form(output_pdf)
    finally:
        if not doc.is_closed:
            doc.close()

    return inspect_noc_form(output_pdf)
