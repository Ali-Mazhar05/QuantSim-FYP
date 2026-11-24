"""QuantSim Simulation service."""

import os

# Path generation is parallel across shards (processes), so each process keeps its linear algebra
# on one thread; set before numpy is first imported by any submodule (B-NFR-14).
os.environ.setdefault("OMP_NUM_THREADS", "1")
