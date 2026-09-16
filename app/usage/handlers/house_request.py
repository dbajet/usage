from __future__ import annotations

from pydantic import BaseModel


class HouseRequest(BaseModel):
    name: str
    timezone: str = ""
    # Which halves of the Realtime view this house has, and therefore which of
    # its settings panels are worth showing.
    shows_sensors: bool = False
    shows_water: bool = False
    shows_power: bool = False
