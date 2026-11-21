"""What the Python reader reads in one note, as plain lines the Swift tests compare with (Swift: NoteLines.swift).
Numbers with 4 decimals, nothing as ∅; an error as 'ERROR <kind>: <message>'."""

from pathlib import Path

from dibekho.excel.delivery_note import DeliveryNoteError, NotDeliveryNote, read_delivery_note


def canon(value) -> str:
    if value is None:
        return "∅"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.4f}"
    return str(value)


def swift_str(s: str) -> str:
    out = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{out}"'


def note_lines(path: Path) -> list[str]:
    try:
        n = read_delivery_note(path)
    except NotDeliveryNote as exc:
        # the message of a file that does not open names the library's own error: only the kind is compared
        text = str(exc)
        return ["ERROR not-a-note: " + ("Không mở được file Excel" if text.startswith("Không mở được file Excel") else text)]
    except DeliveryNoteError as exc:
        return [f"ERROR invalid: {exc}"]
    out = [f"code={n.code}|date={n.doc_date.isoformat()}|customer={n.customer_name}|phone={n.phone}|contact={n.contact}"
           f"|address={n.address}|tax_code={n.tax_code}|email={n.email}|currency={n.currency}|total={canon(n.total)}",
           f"title={n.title}", "letterhead=" + " / ".join(n.letterhead)]
    for ln in n.lines:
        places = ";".join(f"{loc}:{canon(q)}" for loc, q in ln.places)
        out.append(f"line row={ln.row}|raw={ln.raw_name}|vi={ln.name_vi}|zh={ln.name_zh}|spec={ln.spec}|qty={canon(ln.qty)}"
                   f"|note={ln.note}|price={canon(ln.unit_price)}|amount={canon(ln.amount)}|code={ln.product_code}"
                   f"|places={places}|key={ln.key}")
    out += [f"skipped={x}" for x in n.skipped_rows]
    out += [f"fee={name}={canon(v)}" for name, v in n.fees]
    out += [f"warning={w}" for w in n.warnings]
    return out
