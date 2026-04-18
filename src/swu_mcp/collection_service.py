from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


def _normalize_number(value: str | int | None) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    i = 0
    while i < len(raw) - 1 and raw[i] == "0" and raw[i + 1].isdigit():
        i += 1
    return raw[i:]


@dataclass(frozen=True)
class OwnedCard:
    set_code: str
    card_number: str
    count: int
    foil_count: int


class CollectionService:
    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self._entries: dict[tuple[str, str], OwnedCard] = {}
        self._loaded = False

    def _load_from_disk(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in payload.get("entries", []):
            key = (str(row.get("set_code", "")).upper(), _normalize_number(row.get("card_number", "")))
            if not key[0] or not key[1]:
                continue
            self._entries[key] = OwnedCard(
                set_code=key[0],
                card_number=key[1],
                count=int(row.get("count", 0)),
                foil_count=int(row.get("foil_count", 0)),
            )

    def _save_to_disk(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": [
                {
                    "set_code": entry.set_code,
                    "card_number": entry.card_number,
                    "count": entry.count,
                    "foil_count": entry.foil_count,
                }
                for entry in self._entries.values()
            ],
        }
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_csv(self, csv_path: str | Path, *, merge: bool = False) -> dict:
        self._load_from_disk()
        resolved = Path(csv_path).expanduser()
        if not resolved.exists():
            return {"ok": False, "error": f"CSV not found: {resolved}"}
        if not merge:
            self._entries = {}
        imported = 0
        skipped = 0
        with resolved.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return {"ok": False, "error": "CSV has no header row"}
            for row in reader:
                set_code = (row.get("Set") or row.get("set") or "").strip().upper()
                card_number = _normalize_number(
                    row.get("CardNumber")
                    or row.get("card_number")
                    or row.get("Number")
                    or ""
                )
                raw_count = row.get("Count") or row.get("count") or "0"
                try:
                    count = int(raw_count)
                except (TypeError, ValueError):
                    count = 0
                raw_foil = str(row.get("IsFoil") or row.get("is_foil") or "").strip().lower()
                is_foil = raw_foil in {"true", "1", "yes", "y"}
                if not set_code or not card_number or count <= 0:
                    skipped += 1
                    continue
                key = (set_code, card_number)
                existing = self._entries.get(key)
                if existing is not None:
                    new_count = existing.count + count
                    new_foil = existing.foil_count + (count if is_foil else 0)
                else:
                    new_count = count
                    new_foil = count if is_foil else 0
                self._entries[key] = OwnedCard(
                    set_code=set_code,
                    card_number=card_number,
                    count=new_count,
                    foil_count=new_foil,
                )
                imported += 1
        self._save_to_disk()
        result = {
            "ok": True,
            "csv_path": str(resolved),
            "merge": merge,
            "rows_imported": imported,
            "rows_skipped": skipped,
        }
        result.update(self.summary())
        return result

    def owned_count(self, set_code: str, card_number: str | int) -> int:
        self._load_from_disk()
        key = (str(set_code).upper().strip(), _normalize_number(card_number))
        entry = self._entries.get(key)
        return entry.count if entry is not None else 0

    def is_owned(self, set_code: str, card_number: str | int, quantity: int = 1) -> bool:
        return self.owned_count(set_code, card_number) >= max(1, int(quantity))

    def summary(self) -> dict:
        self._load_from_disk()
        by_set: dict[str, int] = {}
        unique_by_set: dict[str, int] = {}
        total = 0
        foil_total = 0
        for entry in self._entries.values():
            by_set[entry.set_code] = by_set.get(entry.set_code, 0) + entry.count
            unique_by_set[entry.set_code] = unique_by_set.get(entry.set_code, 0) + 1
            total += entry.count
            foil_total += entry.foil_count
        return {
            "total_cards": total,
            "unique_entries": len(self._entries),
            "foil_cards": foil_total,
            "by_set": dict(sorted(by_set.items(), key=lambda kv: -kv[1])),
            "unique_by_set": unique_by_set,
            "storage_path": str(self.storage_path),
            "has_data": bool(self._entries),
        }

    def list_entries(self, *, set_code: str | None = None, limit: int = 100) -> list[dict]:
        self._load_from_disk()
        filtered = self._entries.values()
        if set_code:
            normalized = set_code.strip().upper()
            filtered = (entry for entry in filtered if entry.set_code == normalized)
        rows = [
            {
                "set_code": entry.set_code,
                "card_number": entry.card_number,
                "count": entry.count,
                "foil_count": entry.foil_count,
            }
            for entry in filtered
        ]
        rows.sort(key=lambda row: (row["set_code"], _natural_key(row["card_number"])))
        if limit > 0:
            rows = rows[:limit]
        return rows

    def clear(self) -> dict:
        self._entries = {}
        self._loaded = True
        if self.storage_path.exists():
            try:
                self.storage_path.unlink()
            except OSError as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": True, "cleared": True, "storage_path": str(self.storage_path)}


def _natural_key(value: str) -> tuple:
    parts: list = []
    buf = ""
    for ch in value:
        if ch.isdigit():
            buf += ch
        else:
            if buf:
                parts.append((0, int(buf)))
                buf = ""
            parts.append((1, ch))
    if buf:
        parts.append((0, int(buf)))
    return tuple(parts)
