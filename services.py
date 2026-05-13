import math
import json
import requests
import io
import logging
import pandas as pd
from datetime import datetime
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

logger = logging.getLogger(__name__)

class DistanceService:
    @staticmethod
    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return int(R * c)

    @staticmethod
    def get_osrm_matrix(locations: list[dict]) -> list[list[int]] | None:
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
            except Exception as e:
                logger.warning(f"OSRM endpoint {base_url} failed: {e}")
                continue
        return None

    def get_distance_matrix(self, locations: list[dict]) -> tuple[list[list[int]], bool]:
        dist_matrix = self.get_osrm_matrix(locations)
        is_real_roads = True
        
        if dist_matrix is None:
            logger.warning("OSRM failed, falling back to Haversine distance")
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
    def parse_request_form(raw_form: dict) -> dict:
        form_data = {k: v[0] for k, v in raw_form.items()}
        list_keys = [
            'supplier_name', 'supplier_lat', 'supplier_lng', 
            'supplier_trucks_count', 'supplier_caps_hidden', 
            'supplier_cons_hidden', 'supplier_fuels_hidden', 'supplier_inventory', 
            'supplier_time_start', 'supplier_time_end',
            'buyer_name', 'buyer_lat', 'buyer_lng', 'buyer_demand',
            'buyer_time_start', 'buyer_time_end', 'buyer_service_time'
        ]
        for k in list_keys:
            form_data[k] = raw_form.get(k, [])
        form_data['is_long_haul'] = raw_form.get('is_long_haul', ['0'])
        return form_data

    @staticmethod
    def time_to_minutes(time_str: str) -> int:
        if not time_str: return 0
        try:
            h, m = map(int, time_str.split(':'))
            return h * 60 + m
        except: return 0

    @staticmethod
    def extract_entities(form_data: dict) -> tuple[list[dict], list[dict]]:
        suppliers = []
        s_names = form_data['supplier_name']
        s_lats = form_data['supplier_lat']
        s_lngs = form_data['supplier_lng']
        s_caps_str = form_data['supplier_caps_hidden']
        s_cons_str = form_data['supplier_cons_hidden']
        s_fuels_str = form_data.get('supplier_fuels_hidden', [])
        s_inv = form_data['supplier_inventory']
        s_start = form_data.get('supplier_time_start', [])
        s_end = form_data.get('supplier_time_end', [])

        for i in range(len(s_names)):
            if s_names[i].strip():
                try: caps_list = [float(x.strip()) for x in s_caps_str[i].split(',') if x.strip()]
                except: caps_list = []
                
                try: cons_list = [float(x.strip()) for x in s_cons_str[i].split(',') if x.strip()]
                except: cons_list = []
                
                try: fuels_list = [x.strip() for x in s_fuels_str[i].split(',') if x.strip()]
                except: fuels_list = []
                
                while len(cons_list) < len(caps_list): cons_list.append(30.0)
                while len(fuels_list) < len(caps_list): fuels_list.append('diesel')
                
                inventory = float(s_inv[i]) if (i < len(s_inv) and s_inv[i]) else 0
                tw_start = DataProcessor.time_to_minutes(s_start[i] if i < len(s_start) else '06:00')
                tw_end = DataProcessor.time_to_minutes(s_end[i] if i < len(s_end) else '20:00')
                
                if caps_list:
                    suppliers.append({
                        'name': s_names[i], 'x': float(s_lats[i]), 'y': float(s_lngs[i]), 
                        'trucks_caps': caps_list, 'trucks_cons': cons_list,
                        'trucks_fuels': fuels_list, 'inventory': inventory,
                        'tw_start': tw_start, 'tw_end': tw_end,
                        'tw_start_str': s_start[i] if i < len(s_start) else '06:00',
                        'tw_end_str': s_end[i] if i < len(s_end) else '20:00'
                    })

        buyers = []
        b_names = form_data['buyer_name']
        b_lats = form_data['buyer_lat']
        b_lngs = form_data['buyer_lng']
        b_demands = form_data['buyer_demand']
        b_start = form_data.get('buyer_time_start', [])
        b_end = form_data.get('buyer_time_end', [])
        b_serv = form_data.get('buyer_service_time', [])
        
        for i in range(len(b_names)):
            if b_names[i].strip():
                tw_start = DataProcessor.time_to_minutes(b_start[i] if i < len(b_start) else '08:00')
                tw_end = DataProcessor.time_to_minutes(b_end[i] if i < len(b_end) else '18:00')
                try: service_time = int(b_serv[i]) if i < len(b_serv) else 15
                except: service_time = 15
                
                buyers.append({
                    'name': b_names[i], 'x': float(b_lats[i]), 'y': float(b_lngs[i]), 
                    'demand': float(b_demands[i]) if b_demands[i] else 0,
                    'tw_start': tw_start, 'tw_end': tw_end, 'service_time': service_time,
                    'tw_start_str': b_start[i] if i < len(b_start) else '08:00',
                    'tw_end_str': b_end[i] if i < len(b_end) else '18:00'
                })
        
        return suppliers, buyers

class VRPSolver:
    def __init__(self, fuel_prices: dict, driver_salary: float, max_shift_hours: float, max_trips: int, distance_service: DistanceService, is_long_haul: bool = False):
        self.fuel_prices = fuel_prices
        self.driver_salary = driver_salary
        self.max_shift_min = int(max_shift_hours * 60)
        self.max_trips = max_trips
        self.distance_service = distance_service
        self.is_long_haul = is_long_haul
        self.speed_kmh = 50.0

    def _create_data_model(self, suppliers: list[dict], buyers: list[dict]) -> tuple[dict, list[dict], bool]:
        data = {}
        locations = []
        for s in suppliers:
            if self.is_long_haul:
                locations.append({'name': s['name'], 'x': s['x'], 'y': s['y'], 'inventory': s['inventory'], 'tw_start': 0, 'tw_end': 10080, 'service_time': 0, 'tw_start_str': s['tw_start_str'], 'tw_end_str': s['tw_end_str']})
            else:
                locations.append({'name': s['name'], 'x': s['x'], 'y': s['y'], 'inventory': s['inventory'], 'tw_start': s['tw_start'], 'tw_end': s['tw_end'], 'service_time': 0, 'tw_start_str': s['tw_start_str'], 'tw_end_str': s['tw_end_str']})
        for b in buyers:
            if self.is_long_haul:
                b_mod = b.copy()
                b_mod['tw_start'] = 0
                b_mod['tw_end'] = 10080
                locations.append(b_mod)
            else:
                locations.append(b)
        
        dist_matrix, is_real_roads = self.distance_service.get_distance_matrix(locations)
        
        data['distance_matrix'] = dist_matrix
        data['demands'] = [0] * len(suppliers) + [int(b['demand'] * 1000) for b in buyers]
        data['time_windows'] = [(loc['tw_start'], loc['tw_end']) for loc in locations]
        data['service_times'] = [loc['service_time'] for loc in locations]

        starts = []; ends = []; vehicle_capacities = []; vehicle_to_depot_map = []; vehicle_metadata = []
        
        # НОВЕ: Генерація "віртуальних клонів" для кожного авто (Multi-trip)
        for i, s in enumerate(suppliers):
            caps = s['trucks_caps']
            cons = s['trucks_cons']
            fuels = s['trucks_fuels']
            for local_idx, (cap, con, fuel) in enumerate(zip(caps, cons, fuels), 1):
                # Клонуємо авто стільки разів, скільки дозволено рейсів
                for trip_idx in range(1, self.max_trips + 1):
                    starts.append(i)
                    ends.append(i)
                    vehicle_to_depot_map.append(i)
                    vehicle_capacities.append(int(cap * 1000))
                    vehicle_metadata.append({
                        'depot_name': s['name'], 
                        'local_id': local_idx, 
                        'trip_id': trip_idx, # Зберігаємо номер рейсу
                        'capacity_t': cap, 
                        'consumption': con, 
                        'fuel_type': fuel
                    })

        data['vehicle_capacities'] = vehicle_capacities
        data['num_vehicles'] = len(vehicle_capacities)
        data['starts'] = starts
        data['ends'] = ends
        data['vehicle_to_depot'] = vehicle_to_depot_map
        data['vehicle_metadata'] = vehicle_metadata
        
        return data, locations, is_real_roads

    def solve(self, suppliers: list[dict], buyers: list[dict]) -> tuple[list[dict], float, float, bool]:
        data, all_locations, is_real_roads = self._create_data_model(suppliers, buyers)
        if data['num_vehicles'] == 0: raise ValueError("Не додано жодного авто!")

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

        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            dist_m = data['distance_matrix'][from_node][to_node]
            travel_time_min = int((dist_m / 1000.0) / self.speed_kmh * 60)
            service_time = data['service_times'][from_node]
            return travel_time_min + service_time
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(
            time_callback_index,
            10080 if self.is_long_haul else 1440, 
            10080 if self.is_long_haul else 1440, 
            False,
            'Time'
        )
        time_dimension = routing.GetDimensionOrDie('Time')

        for vehicle_id in range(data['num_vehicles']):
            depot_idx = data['vehicle_to_depot'][vehicle_id]
            tw = data['time_windows'][depot_idx]
            time_dimension.CumulVar(routing.Start(vehicle_id)).SetRange(tw[0], tw[1])
            time_dimension.CumulVar(routing.End(vehicle_id)).SetRange(tw[0], tw[1])

        for location_idx, time_window in enumerate(data['time_windows']):
            if location_idx < len(suppliers): continue 
            index = manager.NodeToIndex(location_idx)
            if index == -1: continue
            time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])

        solver = routing.solver()
        
        # НОВЕ: Математика для Multi-trip VRP
        # Групуємо віртуальні авто (рейси) за їхніми фізичними авто
        physical_vehicles = {}
        for v in range(data['num_vehicles']):
            pid = (data['vehicle_metadata'][v]['depot_name'], data['vehicle_metadata'][v]['local_id'])
            if pid not in physical_vehicles: physical_vehicles[pid] = []
            physical_vehicles[pid].append(v)
            
        for pid, v_list in physical_vehicles.items():
            first_v = v_list[0]
            last_v = v_list[-1]
            
            # 1. Загальний час зміни фізичного авто не може перевищувати ліміт (лише якщо не далекобійник)
            if not self.is_long_haul:
                solver.Add(
                    time_dimension.CumulVar(routing.End(last_v)) - time_dimension.CumulVar(routing.Start(first_v)) <= self.max_shift_min
                )
            
            # 2. Рейси однієї машини мають йти строго послідовно
            for i in range(len(v_list) - 1):
                v_curr = v_list[i]
                v_next = v_list[i+1]
                solver.Add(
                    time_dimension.CumulVar(routing.Start(v_next)) >= time_dimension.CumulVar(routing.End(v_curr))
                )

        depots_vehicles = {}
        for v_id, depot_idx in enumerate(data['vehicle_to_depot']):
            if depot_idx not in depots_vehicles: depots_vehicles[depot_idx] = []
            depots_vehicles[depot_idx].append(v_id)
        for depot_idx, vehicles in depots_vehicles.items():
            inv_kg = int(suppliers[depot_idx]['inventory'] * 1000)
            vehicle_loads = [capacity_dimension.CumulVar(routing.End(v)) for v in vehicles]
            solver.Add(solver.Sum(vehicle_loads) <= inv_kg)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_parameters.time_limit.seconds = 10

        logger.info(f"Запуск солвера Multi-Trip VRPTW...")
        solution = routing.SolveWithParameters(search_parameters)
        
        if not solution:
            raise ValueError("Не вдалося побудувати маршрут. Спробуйте розширити вікна або додати більше рейсів/авто.")

        def min_to_str(minutes: int) -> str:
            return f"{minutes // 60:02d}:{minutes % 60:02d}"

        routes_output = []; total_distance_all = 0; total_fuel_cost_all = 0
        
        for vehicle_id in range(data['num_vehicles']):
            index = routing.Start(vehicle_id)
            route_steps = []; route_dist = 0; segment_dist = 0
            meta = data['vehicle_metadata'][vehicle_id]
            current_fuel_price = self.fuel_prices.get(meta['fuel_type'], 0)
            
            start_node = manager.IndexToNode(index)
            home_depot_name = all_locations[start_node]['name']
            
            current_time_min = all_locations[start_node].get('tw_start', 480)
            if not self.is_long_haul:
                current_time_min = solution.Min(time_dimension.CumulVar(index))
            shift_worked_min = 0

            while not routing.IsEnd(index):
                time_var = time_dimension.CumulVar(index)
                
                if not self.is_long_haul:
                    arrival_min = solution.Min(time_var)
                else:
                    arrival_min = current_time_min
                
                node_index = manager.IndexToNode(index)
                loc = all_locations[node_index]
                is_depot = (node_index < len(suppliers))
                
                route_steps.append({
                    'name': loc['name'], 'lat': loc['x'], 'lng': loc['y'], 
                    'unload': data['demands'][node_index] / 1000, 
                    'type': 'depot' if is_depot else 'client', 
                    'dist_from_prev': round(segment_dist / 1000, 2),
                    'arrival_time': min_to_str(arrival_min),
                    'service_time': loc.get('service_time', 0),
                    'tw_start': loc.get('tw_start_str', ''),
                    'tw_end': loc.get('tw_end_str', '')
                })
                prev_index = index
                index = solution.Value(routing.NextVar(index))
                segment_dist = routing.GetArcCostForVehicle(prev_index, index, vehicle_id)
                route_dist += segment_dist
                
                if self.is_long_haul:
                    travel_time_min = int((segment_dist / 1000.0) / self.speed_kmh * 60)
                    
                    while shift_worked_min + travel_time_min > self.max_shift_min:
                        drive_before_sleep = self.max_shift_min - shift_worked_min
                        current_time_min += drive_before_sleep
                        travel_time_min -= drive_before_sleep
                        
                        sleep_dur = 24 * 60 - self.max_shift_min
                        route_steps.append({
                            'name': '🛑 Ночівля в дорозі',
                            'lat': loc['x'], 'lng': loc['y'],
                            'unload': 0, 'type': 'sleep',
                            'dist_from_prev': round((segment_dist * (drive_before_sleep / (travel_time_min + drive_before_sleep))) / 1000, 2),
                            'arrival_time': min_to_str(current_time_min),
                            'service_time': sleep_dur,
                            'tw_start': '', 'tw_end': ''
                        })
                        current_time_min += sleep_dur
                        shift_worked_min = 0
                        
                    current_time_min += travel_time_min
                    shift_worked_min += travel_time_min
                    
                    next_node_index = manager.IndexToNode(index)
                    service_t = all_locations[next_node_index].get('service_time', 0)
                    
                    if shift_worked_min + service_t > self.max_shift_min and not routing.IsEnd(index):
                        sleep_dur = 24 * 60 - self.max_shift_min
                        route_steps.append({
                            'name': f"🛑 Ночівля (біля {all_locations[next_node_index]['name']})",
                            'lat': all_locations[next_node_index]['x'], 'lng': all_locations[next_node_index]['y'],
                            'unload': 0, 'type': 'sleep',
                            'dist_from_prev': 0,
                            'arrival_time': min_to_str(current_time_min),
                            'service_time': sleep_dur,
                            'tw_start': '', 'tw_end': ''
                        })
                        current_time_min += sleep_dur
                        shift_worked_min = 0
                        
                    current_time_min += service_t
                    shift_worked_min += service_t

            end_time_var = time_dimension.CumulVar(index)
            if not self.is_long_haul:
                end_arrival_min = solution.Min(end_time_var)
            else:
                end_arrival_min = current_time_min
            
            route_steps.append({
                'name': all_locations[manager.IndexToNode(index)]['name'], 
                'lat': all_locations[manager.IndexToNode(index)]['x'], 'lng': all_locations[manager.IndexToNode(index)]['y'], 
                'unload': 0, 'type': 'finish', 'dist_from_prev': round(segment_dist / 1000, 2),
                'arrival_time': min_to_str(end_arrival_min)
            })
            
            # Якщо рейс не порожній (дистанція > 0), додаємо його до фінального звіту
            if route_dist > 0:
                dist_km = route_dist / 1000
                fuel_cost = (dist_km / 100) * meta['consumption'] * current_fuel_price
                driver_cost = dist_km * self.driver_salary
                
                # Додаємо маркування рейсу прямо у назву, щоб HTML підхопив це автоматично
                display_id = f"{meta['local_id']} (Рейс {meta['trip_id']})"
                
                routes_output.append({
                    'local_id': display_id, 'home_depot': home_depot_name, 
                    'max_capacity': meta['capacity_t'], 'consumption': meta['consumption'], 
                    'fuel_type': meta['fuel_type'], 'steps': route_steps, 
                    'total_load': sum(s['unload'] for s in route_steps), 
                    'distance_km': round(dist_km, 2), 'fuel_cost': round(fuel_cost, 2), 
                    'driver_cost': round(driver_cost, 2), 'cost': round(fuel_cost + driver_cost, 2),
                    'route_duration_min': end_arrival_min - DataProcessor.time_to_minutes(route_steps[0]['arrival_time'])
                })
                total_distance_all += dist_km
                total_fuel_cost_all += fuel_cost
        
        return routes_output, total_distance_all, total_fuel_cost_all, is_real_roads

class ReportService:
    @staticmethod
    def generate_excel(calculation, data: dict) -> io.BytesIO:
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
                fuel_str = str(route.get('fuel_type', 'diesel')).upper()
                
                details.append({
                    'Фура': f"{home} - Авто №{route['local_id']} [{fuel_str}, Витрата: {cons}л]", 
                    'Точка': f"Всього: {route['distance_km']} км", 
                    'Прибуття': f"Час у рейсі: {route.get('route_duration_min', 0)} хв", 
                    'Операція': f"Вартість: {route['cost']} грн"
                })
                for i, step in enumerate(route['steps'], 1):
                    op = f"Вивант. {step['unload']} т" if step['unload'] > 0 else ""
                    dist = f"+{step['dist_from_prev']} км" if step.get('dist_from_prev', 0) > 0 else "-"
                    arr = step.get('arrival_time', '-')
                    details.append({
                        'Фура': route['local_id'], '№': i, 'Точка': step['name'], 
                        'Прибуття': arr, 'Операція': op, 'Проїхав': dist
                    })
                details.append({})
            pd.DataFrame(details).to_excel(writer, sheet_name='Маршрути', index=False)
        output.seek(0)
        return output