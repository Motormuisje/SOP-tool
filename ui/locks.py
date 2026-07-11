"""Shared inter-route locks.

``engine_rebuild_lock`` serializes every full engine build/install:
/api/calculate, dynamic-product CRUD, structural config rebuilds and the
session-switch restore path. Rebuilds take seconds and swap ``sess['engine']``
plus the baseline/override stores; two running concurrently would race on
those and leave a half-installed engine. RLock so a locked path may call
helpers that also take the lock.
"""

import threading

engine_rebuild_lock = threading.RLock()
