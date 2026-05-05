import math
import json
import requests
import io
import pandas as pd
from datetime import datetime
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

class DistanceService:
    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000  # Earth radius in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return int(R * c)

    @staticmethod
    def get_osrm_matrix(locations):
        coords_str = ";".join([f"{loc['y']},{loc['x']}" for loc in locations])
        endpoints = [
            "http://router.project-osrm.org/table/v1/driving/",
            "https://routing.openstreetmap.de/routed-car/table/v1/driving/"
        ]
        
        for base_url in endpoints:
            try:
                response = requests.get(f"{base_url}{coords_str}?annotations=distance", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if 'distances' in data:
                        return [[int(d) for d in row] for row in data['distances']]
            except:
                continue
        return None

    def get_distance_matrix(self, locations):
        # Try OSRM
        dist_matrix = self.get_osrm_matrix(locations)
        is_real_roads = True
        
        # Fallback to Haversine
        if dist_matrix is None:
            is_real_roads = False
            dist_matrix = []
            for from_node in locations:
                row = []
                for to_node in locations:
                    dist = self.haversine(from_node['x'], from_node['y'], to_node['x'], to_node['y'])
                    row.append(dist)
                dist_matrix.append(row)
        
        return dist_matrix, is_real_roads

class DataProcessor:
    @staticmethod
    def parse_request_form(raw_form):
        form_data = {k: v[0] for k, v in raw_form.items()}
        list_keys = [
            'supplier_name', 'supplier_lat', 'supplier_lng', 
            'supplier_trucks_count', 'supplier_caps_hidden', 
            'supplier_cons_hidden', 'supplier_inventory', 
            'buyer_name', 'buyer_lat', 'buyer_lng', 'buyer_demand'
        ]
        for k in list_keys:
            form_data[k] = raw_form.get(k, [])
        return form_data

    @staticmethod
    def extract_entities(form_data):
        suppliers = []
        s_names = form_data['supplier_name']
        s_lats = form_data['supplier_lat']
        s_lngs = form_data['supplier_lng']
        s_caps_str = form_data['supplier_caps_hidden']
        s_cons_str = form_data['supplier_cons_hidden']
        s_inv = form_data['supplier_inventory']

        for i in range(len(s_names)):
            if s_names[i].strip():
                try:
                    caps_list = [float(x.strip()) for x in s_caps_str[i].split(',') if x.strip()]
                    cons_list = [float(x.strip()) for x in s_cons_str[i].split(',') if x.strip()]
                except:
                    caps_list = []
                    cons_list = []
                
                while len(cons_list) < len(caps_list):
                    cons_list.append(30.0)
                
                inventory = float(s_inv[i]) if (i < len(s_inv) and s_inv[i]) else 0
                if caps_list:
                    suppliers.append({
                        'name': s_names[i], 
                        'x': float(s_lats[i]), 
                        'y': float(s_lngs[i]), 
                        'trucks_caps': caps_list, 
                        'trucks_cons': cons_list, 
                        'inventory': inventory
                    })

        buyers = []
        b_names = form_data['buyer_name']
        b_lats = form_data['buyer_lat']
        b_lngs = form_data['buyer_lng']
        b_demands = form_data['buyer_demand']
        for i in range(len(b_names)):
            if b_names[i].strip():
                buyers.append({
                    'name': b_names[i], 
                    'x': float(b_lats[i]), 
                    'y': float(b_lngs[i]), 
                    'demand': float(b_demands[i]) if b_demands[i] else 0
                })
        
        return suppliers, buyers

class VRPSolver:
    def __init__(self, fuel_price, driver_salary):
        self.fuel_price = fuel_price
        self.driver_salary = driver_salary
        self.distance_service = DistanceService()

    def _create_data_model(self, suppliers, buyers):
        data = {}
        locations = []
        for s in suppliers:
            locations.append({'name': s['name'], 'x': s['x'], 'y': s['y'], 'inventory': s['inventory']})
        for b in buyers:
            locations.append({'name': b['name'], 'x': b['x'], 'y': b['y']})
        
        dist_matrix, is_real_roads = self.distance_service.get_distance_matrix(locations)
        
        data['distance_matrix'] = dist_matrix
        data['demands'] = [0] * len(suppliers) + [int(b['demand'] * 1000) for b in buyers]

        starts = []; ends = []; vehicle_capacities = []; vehicle_to_depot_map = []; vehicle_metadata = []
        for i, s in enumerate(suppliers):
            caps = s['trucks_caps']
            cons = s['trucks_cons']
            for local_idx, (cap, con) in enumerate(zip(caps, cons), 1):
                starts.append(i)
                ends.append(i)
                vehicle_to_depot_map.append(i)
                vehicle_capacities.append(int(cap * 1000))
                vehicle_metadata.append({
                    'depot_name': s['name'], 
                    'local_id': local_idx, 
                    'capacity_t': cap, 
                    'consumption': con
                })

        data['vehicle_capacities'] = vehicle_capacities
        data['num_vehicles'] = len(vehicle_capacities)
        data['starts'] = starts
        data['ends'] = ends
        data['vehicle_to_depot'] = vehicle_to_depot_map
        data['vehicle_metadata'] = vehicle_metadata
        
        return data, locations, is_real_roads

    def solve(self, suppliers, buyers):
        data, all_locations, is_real_roads = self._create_data_model(suppliers, buyers)
        
        if data['num_vehicles'] == 0:
            raise ValueError("Не додано жодного авто!")

        manager = pywrapcp.RoutingIndexManager(len(data['distance_matrix']), data['num_vehicles'], data['starts'], data['ends'])
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            return data['distance_matrix'][manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
        
        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        def demand_callback(from_index):
            return data['demands'][manager.IndexToNode(from_index)]
        
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(demand_callback_index, 0, data['vehicle_capacities'], True, 'Capacity')
        capacity_dimension = routing.GetDimensionOrDie('Capacity')

        solver = routing.solver()
        depots_vehicles = {}
        for v_id, depot_idx in enumerate(data['vehicle_to_depot']):
            if depot_idx not in depots_vehicles:
                depots_vehicles[depot_idx] = []
            depots_vehicles[depot_idx].append(v_id)
        
        for depot_idx, vehicles in depots_vehicles.items():
            inv_kg = int(suppliers[depot_idx]['inventory'] * 1000)
            vehicle_loads = [capacity_dimension.CumulVar(routing.End(v)) for v in vehicles]
            solver.Add(solver.Sum(vehicle_loads) <= inv_kg)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_parameters.time_limit.seconds = 10

        solution = routing.SolveWithParameters(search_parameters)
        
        if not solution:
            raise ValueError("Не вдалося побудувати маршрут.")

        routes_output = []
        total_distance_all = 0
        total_fuel_cost_all = 0
        
        for vehicle_id in range(data['num_vehicles']):
            index = routing.Start(vehicle_id)
            route_steps = []
            route_dist = 0
            segment_dist = 0
            meta = data['vehicle_metadata'][vehicle_id]
            consumption = meta['consumption']
            start_node = manager.IndexToNode(index)
            home_depot_name = all_locations[start_node]['name']

            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                loc = all_locations[node_index]
                is_depot = (node_index < len(suppliers))
                route_steps.append({
                    'name': loc['name'], 
                    'lat': loc['x'], 
                    'lng': loc['y'], 
                    'unload': data['demands'][node_index] / 1000, 
                    'type': 'depot' if is_depot else 'client', 
                    'dist_from_prev': round(segment_dist / 1000, 2)
                })
                prev_index = index
                index = solution.Value(routing.NextVar(index))
                segment_dist = routing.GetArcCostForVehicle(prev_index, index, vehicle_id)
                route_dist += segment_dist

            route_steps.append({
                'name': all_locations[manager.IndexToNode(index)]['name'], 
                'lat': all_locations[manager.IndexToNode(index)]['x'], 
                'lng': all_locations[manager.IndexToNode(index)]['y'], 
                'unload': 0, 
                'type': 'finish', 
                'dist_from_prev': round(segment_dist / 1000, 2)
            })
            
            if route_dist > 0:
                dist_km = route_dist / 1000
                fuel_cost = (dist_km / 100) * consumption * self.fuel_price
                driver_cost = dist_km * self.driver_salary
                routes_output.append({
                    'local_id': meta['local_id'], 
                    'home_depot': home_depot_name, 
                    'max_capacity': meta['capacity_t'], 
                    'consumption': consumption, 
                    'steps': route_steps, 
                    'total_load': sum(s['unload'] for s in route_steps), 
                    'distance_km': round(dist_km, 2), 
                    'fuel_cost': round(fuel_cost, 2), 
                    'driver_cost': round(driver_cost, 2), 
                    'cost': round(fuel_cost + driver_cost, 2)
                })
                total_distance_all += dist_km
                total_fuel_cost_all += fuel_cost
        
        return routes_output, total_distance_all, total_fuel_cost_all, is_real_roads

class ReportService:
    @staticmethod
    def generate_excel(calculation, data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            method_str = "Реальні дороги" if data.get('is_real_roads', True) else "GPS (Пряма лінія)"
            summary_data = [
                {'Параметр': 'Дата', 'Значення': calculation.date.strftime('%Y-%m-%d %H:%M')}, 
                {'Параметр': 'Метод', 'Значення': method_str}, 
                {'Параметр': 'Дистанція', 'Значення': f"{data['total_km']} км"}, 
                {'Параметр': 'Вартість', 'Значення': f"{data['total_cost']} грн"}
            ]
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Звіт', index=False)
            
            details = []
            for route in data['routes']:
                home = route.get('home_depot', 'Склад')
                cons = route.get('consumption', '?')
                details.append({
                    'Фура': f"{home} - Авто №{route['local_id']} [Витрата: {cons}л]", 
                    'Точка': f"Всього: {route['distance_km']} км", 
                    'Прибуття': '', 
                    'Операція': f"Вартість: {route['cost']} грн"
                })
                for i, step in enumerate(route['steps'], 1):
                    op = f"Вивант. {step['unload']} т" if step['unload'] > 0 else ""
                    dist = f"+{step['dist_from_prev']} км" if step.get('dist_from_prev', 0) > 0 else "-"
                    details.append({
                        'Фура': route['local_id'], 
                        '№': i, 
                        'Точка': step['name'], 
                        'Прибуття': '-', 
                        'Операція': op, 
                        'Проїхав': dist
                    })
                details.append({})
            pd.DataFrame(details).to_excel(writer, sheet_name='Маршрути', index=False)
        output.seek(0)
        return output
