from __future__ import annotations

from chia.server.start_service import Service
from chia.solver.solver import Solver
from chia.solver.solver_api import SolverAPI
from chia.solver.solver_rpc_api import SolverRpcApi

SolverService = Service[Solver, SolverAPI, SolverRpcApi]
