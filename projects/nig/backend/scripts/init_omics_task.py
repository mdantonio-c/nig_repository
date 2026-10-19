#!/usr/bin/python3
"""Send one periodic Omics Celery task (poll or cleanup report) from cron.

Usage: ``init_omics_task.py omics_poll_tasks|omics_cleanup``. With
``OMICS_ENABLE=0`` (default) the script exits without sending anything.
"""

import sys
from typing import Optional, Sequence

from restapi.connectors import celery
from restapi.env import Env
from restapi.utilities.logs import log

ALLOWED_TASKS = ("omics_poll_tasks", "omics_cleanup")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in ALLOWED_TASKS:
        log.error("Usage: init_omics_task.py {}", "|".join(ALLOWED_TASKS))
        return 2
    if not Env.get_bool("OMICS_ENABLE", False):
        log.info("OMICS_ENABLE is off, {} not sent", args[0])
        return 0
    celery.get_instance().celery_app.send_task(args[0], countdown=1)
    log.info("Sent {}", args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
