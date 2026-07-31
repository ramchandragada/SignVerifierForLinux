"""Detect and fill Amazon blank NOC AcroForm fields.

Amazon issues digitally signed blank NOCs to service providers. The SP fills
merchant details into AcroForm text fields, then verifies the signature.
Filling is an incremental update — crypto stays intact; Adobe/pyHanko report
MODIFIED (expected for this workflow).

Known field names on Amazon FC NOCs:
  CurrentDate, SellerName (two widgets M/S + M/s. sharing one value),
  AddressLine1, AddressLine2, Signature1
"""

from __future__ import annotations

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


@dataclass
class NocFormStatus:
    """Amazon NOC fillable-form status for the UI."""

    is_amazon_noc: bool
    needs_fill: bool
    complete: bool
    fields: list[NocFieldSnapshot] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_amazon_noc": self.is_amazon_noc,
            "needs_fill": self.needs_fill,
            "complete": self.complete,
            "message": self.message,
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
            # e.g. /Parent 4 0 R
            m = re.search(r"/Parent\s+(\d+)\s+0\s+R", obj)
            if m:
                parent = int(m.group(1))
                parent_obj = doc.xref_object(parent)
                vm = re.search(r"/V\s*\((.*?)\)", parent_obj, re.DOTALL)
                if vm:
                    return _clean(vm.group(1).replace("\\)", ")").replace("\\(", "("))
                # PDF literal hex string uncommon here; also try get_key
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


def inspect_noc_form(path: str | Path) -> NocFormStatus:
    """Inspect a PDF for Amazon blank-NOC AcroForm fields."""
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
        if not is_amazon:
            return NocFormStatus(
                is_amazon_noc=False,
                needs_fill=False,
                complete=False,
                message="",
            )

        date_vals = values.get(FIELD_DATE, [""])
        seller_vals = values.get(FIELD_SELLER, [""])
        addr1_vals = values.get(FIELD_ADDR1, [""])
        addr2_vals = values.get(FIELD_ADDR2, [""])

        # SellerName kids share one parent /V — same merchant on M/S and M/s.
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
            ),
            NocFieldSnapshot(
                name="address_line2",
                label="Address line 2 (optional)",
                value=addr2_v,
                filled=bool(addr2_v),
                editable=True,
            ),
        ]

        required_ok = bool(date_v and seller and addr1_v)
        needs_fill = not required_ok

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
            needs_fill=needs_fill,
            complete=required_ok,
            fields=fields,
            message=msg,
        )
    finally:
        doc.close()


def _set_text_field(doc: fitz.Document, widget: fitz.Widget, value: str) -> None:
    """Write a text widget value (updates parent /V when kids share a name)."""
    widget.field_value = value
    widget.update()
    # Ensure parent /V is set for SellerName-style kids.
    try:
        obj = doc.xref_object(widget.xref)
        m = re.search(r"/Parent\s+(\d+)\s+0\s+R", obj)
        if m:
            parent = int(m.group(1))
            # PDF string escape
            escaped = (
                value.replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )
            doc.xref_set_key(parent, "V", f"({escaped})")
    except Exception:
        pass


def fill_noc_form(
    source_pdf: str | Path,
    output_pdf: str | Path,
    *,
    date: str,
    ms_name: str,
    ms_name_2: str | None = None,
    address: str,
    address_line2: str = "",
) -> NocFormStatus:
    """Write merchant details into Amazon NOC AcroForm fields (incremental)."""
    source_pdf = Path(source_pdf)
    output_pdf = Path(output_pdf)

    date_v = _clean(date)
    name1 = _clean(ms_name)
    name2 = _clean(ms_name_2) if ms_name_2 is not None else name1
    # PDF has one shared SellerName /V for both M/S widgets.
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
