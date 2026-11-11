from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, conlist, confloat
from typing import List
import uvicorn

from solver.vrp_solver import solve_vrp

app = FastAPI(title="Logistics Route Optimizer", version="1.0.0")

class Stop(BaseModel):
    lat: confloat(ge=-90, le=90)
    lon: confloat(ge=-180, le=180)
    demand: conlist(int, min_items=1, max_items=1)

class FleetVehicle(BaseModel):
    capacity: int
    max_distance: float

class SolveRequest(BaseModel):
    depot: Stop
    stops: List[Stop]
    fleet: List[FleetVehicle]

class Route(BaseModel):
    vehicle_id: int
    stop_indices: List[int]
    total_distance: float

class SolveResponse(BaseModel):
    routes: List[Route]
    total_distance: float

@app.post("/solve", response_model=SolveResponse)
async def solve(request: SolveRequest):
    try:
        routes, total = solve_vrp(request.depot, request.stops, request.fleet)
        response_routes = [
            Route(vehicle_id=i, stop_indices=r["stops"], total_distance=r["distance"])
            for i, r in enumerate(routes)
        ]
        return SolveResponse(routes=response_routes, total_distance=total)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
