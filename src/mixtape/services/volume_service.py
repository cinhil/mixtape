"""Volume listing helper used by the libraries / register-USB UI flows.

The watcher service emits change *events*; this one answers point-in-time
"what's plugged in right now?" queries from clients."""
from __future__ import annotations

import asyncio
from typing import Any

from ..library_marker import find_marker_on_volume
from ..platform_io import detect_backend


class VolumeService:
    def __init__(self) -> None:
        self._backend = detect_backend()

    async def list(self) -> list[dict[str, Any]]:
        """Return all currently-mounted volumes that look user-relevant
        (removable / mounted in /Volumes / under /media), enriched with
        a marker descriptor if a ``.mixtape`` file is detectable."""
        from pathlib import Path
        vols = await asyncio.to_thread(self._backend.list_volumes)
        # Probe markers in parallel — each call is a filesystem walk +
        # YAML parse, fine to fan out for a handful of volumes.
        marker_hits = await asyncio.gather(*(
            asyncio.to_thread(find_marker_on_volume, Path(str(v.mount_path)))
            for v in vols
        ))
        out: list[dict[str, Any]] = []
        for v, hit in zip(vols, marker_hits):
            marker = None
            if hit is not None:
                m, root = hit
                marker = {"name": m.name, "uuid": m.uuid, "root": str(root)}
            out.append({
                "identifier": v.identifier,
                "label": v.label,
                "mount_path": str(v.mount_path),
                "fs_type": v.fs_type,
                "size_bytes": v.size_bytes,
                "free_bytes": v.free_bytes,
                "is_removable": v.is_removable,
                "marker": marker,
            })
        return out
