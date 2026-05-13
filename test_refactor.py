from services import VRPSolver

def test_solver():
    suppliers = [
        {
            'name': 'Depot 1', 
            'x': 50.4501, 
            'y': 30.5234, 
            'trucks_caps': [10.0, 15.0], 
            'trucks_cons': [25.0, 30.0], 
            'inventory': 100.0
        }
    ]
    buyers = [
        {'name': 'Buyer 1', 'x': 50.4550, 'y': 30.5300, 'demand': 5.0},
        {'name': 'Buyer 2', 'x': 50.4600, 'y': 30.5400, 'demand': 8.0}
    ]
    
    fuel_price = 50.0
    driver_salary = 10.0
    
    solver = VRPSolver(fuel_price, driver_salary)
    routes, total_km, total_fuel, is_real_roads = solver.solve(suppliers, buyers)
    
    print(f"Total KM: {total_km}")
    print(f"Total Fuel: {total_fuel}")
    print(f"Is Real Roads: {is_real_roads}")
    print(f"Routes Count: {len(routes)}")
    
    assert len(routes) > 0
    assert total_km > 0
    print("Test passed!")

if __name__ == "__main__":
    try:
        test_solver()
    except Exception as e:
        print(f"Test failed: {e}")
