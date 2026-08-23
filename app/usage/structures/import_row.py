from __future__ import annotations

from typing import Any, NamedTuple


class ImportRow(NamedTuple):
    read_on: str
    edf: float
    gdf: float
    water: float
    hc: float | None
    hp: float | None

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "read_on": self.read_on,
            "edf": self.edf,
            "gdf": self.gdf,
            "water": self.water,
            "hc": self.hc,
            "hp": self.hp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImportRow:
        return cls(
            read_on=str(data.get("read_on") or ""),
            edf=float(data.get("edf") or 0),
            gdf=float(data.get("gdf") or 0),
            water=float(data.get("water") or 0),
            hc=float(data["hc"]) if data.get("hc") is not None else None,
            hp=float(data["hp"]) if data.get("hp") is not None else None,
        )
