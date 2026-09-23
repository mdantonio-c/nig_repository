import os
import re
import shutil
from datetime import datetime

from plumbum import local

from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.endpoints.schemas import StatsSchema, StatsType
from restapi.rest.definition import Response
from restapi.services.authentication import Role, User


class NIGAdminStats(NIGEndpoint):
    """Expose consistent disk statistics on container filesystems."""

    labels = ["helpers"]
    depends_on = ["AUTH_ENABLE"]
    private = True

    @decorators.auth.require_all(Role.ADMIN)
    @decorators.marshal_with(StatsSchema(), code=200)
    @decorators.endpoint(
        path="/admin/stats",
        summary="Retrieve stats from the server",
        responses={"200": "Stats retrieved"},
    )
    def get(self, user: User) -> Response:
        load_percentage = (100 * os.getloadavg()[-1]) / (os.cpu_count() or 1)

        vmstat = local["vmstat"]
        vmstat_out1 = re.split(r"\s+", vmstat().split("\n")[2])
        vmstat_out1 = {key: value for key, value in enumerate(vmstat_out1)}
        vmstat_out2 = vmstat(["-s", "-S", "M"]).split("\n")

        boot_time = datetime.fromtimestamp(int(vmstat_out2[24].strip().split(" ")[0]))

        total, _, free = shutil.disk_usage("/")
        used = total - free

        statistics: StatsType = {
            "system": {"boot_time": boot_time},
            "cpu": {
                "count": os.cpu_count() or 0,
                "load_percentage": load_percentage,
                "user": vmstat_out1.get(13, 0),
                "system": vmstat_out1.get(14, 0),
                "idle": vmstat_out1.get(15, 0),
                "wait": vmstat_out1.get(16, 0),
                "stolen": vmstat_out1.get(17, 0),
            },
            "ram": {
                "total": vmstat_out2[0].strip().split(" ")[0],
                "used": vmstat_out2[1].strip().split(" ")[0],
                "active": vmstat_out2[2].strip().split(" ")[0],
                "inactive": vmstat_out2[3].strip().split(" ")[0],
                "free": vmstat_out2[4].strip().split(" ")[0],
                "buffer": vmstat_out2[5].strip().split(" ")[0],
                "cache": vmstat_out2[6].strip().split(" ")[0],
            },
            "swap": {
                "from_disk": vmstat_out1.get(7, 0),
                "to_disk": vmstat_out1.get(8, 0),
                "total": vmstat_out2[7].strip().split(" ")[0],
                "used": vmstat_out2[8].strip().split(" ")[0],
                "free": vmstat_out2[9].strip().split(" ")[0],
            },
            "disk": {
                "total_disk_space": total / 1024**3,
                "used_disk_space": used / 1024**3,
                "free_disk_space": free / 1024**3,
                "occupacy": 100 * used / total,
            },
            "procs": {
                "waiting_for_run": vmstat_out1.get(1, 0),
                "uninterruptible_sleep": vmstat_out1.get(2, 0),
            },
            "io": {
                "blocks_received": vmstat_out1.get(9, 0),
                "blocks_sent": vmstat_out1.get(10, 0),
            },
            "network_latency": {"min": 0, "avg": 0, "max": 0},
        }

        return self.response(statistics)
