from __future__ import annotations

from typing import Any

from app.database import loads_json


def row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key, value in list(data.items()):
        if key.endswith("_json"):
            data[key[:-5]] = loads_json(value, {})
            del data[key]
    return data
