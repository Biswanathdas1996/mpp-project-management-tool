"""RQ worker entry point.

The JVM (MPXJ) is started once on the main thread *before* any job runs, and jobs execute in the
same process (SimpleWorker): forking after the JVM has started is unsafe, and a JVM started from a
job thread would block clean shutdown.

    python -m app.worker
"""
from __future__ import annotations

import logging

from redis import Redis
from rq import Queue
from rq.worker import SimpleWorker

from .config import get_settings
from .main import bootstrap
from .parser.mpp_parser import mpxj_classes


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    bootstrap()
    mpxj_classes()
    conn = Redis.from_url(s.redis_url)
    worker = SimpleWorker([Queue(s.queue_name, connection=conn)], connection=conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
