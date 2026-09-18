from __future__ import annotations

from pydantic import BaseModel


class HouseRequest(BaseModel):
    name: str
    timezone: str = ""
    # Which halves of the Realtime view this house has, and therefore which of
    # its settings panels are worth showing. Thermometers take two: a house is
    # pushed to by Home Assistant, pulled from SwitchBot's cloud, or both, and
    # one switch for the pair would have to be labelled as one of them.
    shows_sensors: bool = False
    shows_switchbot: bool = False
    shows_water: bool = False
    shows_power: bool = False
