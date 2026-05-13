from flask import Flask, render_template, request, send_file, redirect, url_for, flash
import json
import os
import logging
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from models import db, Calculation, User, RouteAssignment, init_db
from services import VRPSolver, DataProcessor, ReportService, DistanceService
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Будь ласка, увійдіть для доступу до цієї сторінки."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

init_db(app)

@app.context_processor
def inject_user():
    return dict(current_user=current_user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password_hash, password):
            login_user(user)
            logger.info(f"Користувач {username} увійшов у систему.")
            if user.role == 'driver':
                return redirect(url_for('my_routes'))
            return redirect(url_for('index'))
        else:
            flash("Неправильний логін або пароль.", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if current_user.role == 'driver':
        return redirect(url_for('my_routes'))
    
    result = None
    form_data = {}
    current_calc_id = None
    routes_json = '[]'
    
    if request.method == 'POST':
        raw_form = request.form.to_dict(flat=False)
        form_data = DataProcessor.parse_request_form(raw_form)
        
        try:
            fuel_prices = {
                'petrol': float(form_data.get('fuel_price_petrol', 0) or 0),
                'diesel': float(form_data.get('fuel_price_diesel', 0) or 0),
                'gas': float(form_data.get('fuel_price_gas', 0) or 0)
            }
            driver_salary = float(form_data.get('driver_salary', 0) or 0)
            max_shift_hours = float(form_data.get('max_shift_hours', 8) or 8)
            
            # НОВЕ: Отримуємо кількість рейсів
            max_trips = int(form_data.get('max_trips', 2) or 2)
            
            suppliers, buyers = DataProcessor.extract_entities(form_data)
            
            if not suppliers:
                raise ValueError("Додайте склад.")
            if not buyers:
                raise ValueError("Додайте клієнтів.")

            logger.info(f"Початок розрахунку Multi-Trip VRPTW: {len(suppliers)} склад(ів), {len(buyers)} клієнт(ів).")

            dist_service = DistanceService()
            
            # Передаємо max_trips та is_long_haul у солвер
            is_long_haul = bool(form_data.get('is_long_haul', ['0'])[0] == '1')
            solver = VRPSolver(fuel_prices, driver_salary, max_shift_hours, max_trips, dist_service, is_long_haul)
            
            routes, total_km, total_fuel, is_real_roads = solver.solve(suppliers, buyers)
            
            total_salary = total_km * driver_salary
            total_cost = total_fuel + total_salary
            
            result = {
                'routes': routes, 
                'total_km': round(total_km, 2), 
                'total_fuel': round(total_fuel, 2), 
                'total_salary': round(total_salary, 2), 
                'total_cost': round(total_cost, 2), 
                'is_real_roads': is_real_roads,
                'inputs': form_data
            }
            
            routes_json = json.dumps(routes)
            
            new_calc = Calculation(
                total_cost=result['total_cost'], 
                total_km=result['total_km'], 
                result_json=json.dumps(result)
            )
            db.session.add(new_calc)
            db.session.commit()
            current_calc_id = new_calc.id
            logger.info(f"Успіх! Розрахунок збережено в БД з ID: {current_calc_id}")
            
        except Exception as e:
            logger.error(f"Помилка під час розрахунку: {str(e)}", exc_info=True)
            result = {'error': str(e)}
            
    drivers = User.query.filter_by(role='driver').all()
    assignments = {}
    return render_template('index.html', result=result, form=form_data, calc_id=current_calc_id, routes_json=routes_json, drivers=drivers, assignments=assignments)

@app.route('/history/<int:calc_id>')
@login_required
def view_calculation(calc_id):
    if current_user.role == 'driver':
        return redirect(url_for('my_routes'))
    calc = Calculation.query.get_or_404(calc_id)
    result = json.loads(calc.result_json)
    form_data = result.get('inputs', {})
    routes_json = json.dumps(result.get('routes', []))
    
    drivers = User.query.filter_by(role='driver').all()
    assign_records = RouteAssignment.query.filter_by(calculation_id=calc_id).all()
    assignments = {a.route_index: a.driver_id for a in assign_records}
    
    return render_template('index.html', result=result, form=form_data, calc_id=calc.id, routes_json=routes_json, drivers=drivers, assignments=assignments)

@app.route('/delete/<int:calc_id>', methods=['POST'])
@login_required
def delete_calculation(calc_id):
    if current_user.role != 'logistician':
        return "Access denied", 403
    calc = Calculation.query.get_or_404(calc_id)
    db.session.delete(calc)
    db.session.commit()
    logger.info(f"Видалено розрахунок з ID: {calc_id}")
    return redirect(url_for('history'))

@app.route('/history')
@login_required
def history():
    if current_user.role == 'driver':
        return redirect(url_for('my_routes'))
    return render_template('history.html', calculations=Calculation.query.order_by(Calculation.date.desc()).all())

@app.route('/export/<int:calc_id>')
@login_required
def export_excel(calc_id):
    if current_user.role != 'logistician':
        return "Access denied", 403
    calc = Calculation.query.get_or_404(calc_id)
    data = json.loads(calc.result_json)
    
    output = ReportService.generate_excel(calc, data)
    filename = f"Route_{calc.id}.xlsx"
    logger.info(f"Згенеровано Excel звіт для розрахунку ID: {calc_id}")
    
    return send_file(
        output, 
        as_attachment=True, 
        download_name=filename, 
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/assign_route', methods=['POST'])
@login_required
def assign_route():
    if current_user.role != 'logistician':
        return "Access denied", 403
    calc_id = request.form.get('calc_id')
    route_index = request.form.get('route_index')
    driver_id = request.form.get('driver_id')
    
    if not all([calc_id, route_index, driver_id]):
        return "Missing data", 400
        
    assignment = RouteAssignment.query.filter_by(calculation_id=calc_id, route_index=route_index).first()
    if assignment:
        assignment.driver_id = driver_id
    else:
        assignment = RouteAssignment(calculation_id=calc_id, route_index=route_index, driver_id=driver_id)
        db.session.add(assignment)
    db.session.commit()
    flash(f"Маршрут №{int(route_index)+1} успішно призначено.", "success")
    return redirect(url_for('view_calculation', calc_id=calc_id))

@app.route('/my_routes')
@login_required
def my_routes():
    if current_user.role != 'driver':
        return redirect(url_for('index'))
    assignments = RouteAssignment.query.filter_by(driver_id=current_user.id).all()
    assigned_data = []
    for a in assignments:
        calc = a.calculation
        result = json.loads(calc.result_json)
        routes = result.get('routes', [])
        if a.route_index < len(routes):
            my_route = routes[a.route_index]
            my_route['route_index'] = a.route_index
            assigned_data.append({
                'calc_id': calc.id,
                'date': calc.date,
                'route_index': a.route_index,
                'route': my_route
            })
    assigned_data.sort(key=lambda x: x['date'], reverse=True)
    return render_template('driver_dashboard.html', assigned_data=assigned_data)

if __name__ == '__main__':
    app.run(debug=True)