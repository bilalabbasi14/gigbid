import math
from typing import List, Tuple, Dict
import networkx as nx

# Helper to compute haversine distance (km)
def haversine(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    R = 6371.0
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def build_complete_graph(depot, stops):
    G = nx.complete_graph(len(stops) + 1)  # node 0 is depot
    positions = [(depot.lat, depot.lon)] + [(s.lat, s.lon) for s in stops]
    for i in G.nodes:
        for j in G.nodes:
            if i < j:
                dist = haversine(positions[i], positions[j])
                G[i][j]['weight'] = dist
    return G, positions

def clarke_wright(G, positions, fleet):
    # Initial routes: each stop its own route
    routes = [{"stops": [i], "load": 1, "distance": 2 * G[0][i]['weight']} for i in range(1, G.number_of_nodes())]
    savings = []
    for i in range(1, G.number_of_nodes()):
        for j in range(i+1, G.number_of_nodes()):
            s = G[0][i]['weight'] + G[0][j]['weight'] - G[i][j]['weight']
            savings.append((s, i, j))
    savings.sort(reverse=True)

    for s, i, j in savings:
        ri = next((r for r in routes if r["stops"][-1] == i), None)
        rj = next((r for r in routes if r["stops"][0] == j), None)
        if ri is None or rj is None or ri is rj:
            continue
        combined_load = ri["load"] + rj["load"]
        # Simple capacity check: use first vehicle capacity as reference
        if combined_load > fleet[0].capacity:
            continue
        # Merge routes
        new_route = {
            "stops": ri["stops"] + rj["stops"],
            "load": combined_load,
            "distance": ri["distance"] + rj["distance"] - s
        }
        routes.remove(ri)
        routes.remove(rj)
        routes.append(new_route)
    return routes

def two_opt(route, G):
    best = route[:]
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                if j - i == 1:
                    continue
                new_route = best[:i] + best[i:j][::-1] + best[j:]
                new_dist = sum(G[new_route[k]][new_route[k+1]]['weight'] for k in range(len(new_route)-1))
                old_dist = sum(G[best[k]][best[k+1]]['weight'] for k in range(len(best)-1))
                if new_dist < old_dist:
                    best = new_route
                    improved = True
        
    return best

def solve_vrp(depot, stops, fleet) -> Tuple[List[Dict], float]:
    G, positions = build_complete_graph(depot, stops)
    initial_routes = clarke_wright(G, positions, fleet)
    final_routes = []
    total_distance = 0.0
    for r in initial_routes:
        seq = [0] + r["stops"] + [0]
        improved_seq = two_opt(seq, G)
        dist = sum(G[improved_seq[k]][improved_seq[k+1]]['weight'] for k in range(len(improved_seq)-1))
        final_routes.append({"stops": improved_seq[1:-1], "distance": dist})
        total_distance += dist
    return final_routes, total_distance
