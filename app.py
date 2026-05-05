from flask import Flask, render_template, request, send_file, redirect, url_for
import json
import os
from models import db, Calculation, init_db
from services import VRPSolver, DataProcessor, ReportService

app = Flask(__name__)

# --- CONFIGURATION ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'logistic.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
init_db(app)

# --- ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    form_data = {}
    current_calc_id = None
    routes_json = '[]'
    
    if request.method == 'POST':
        raw_form = request.form.to_dict(flat=False)
        form_data = DataProcessor.parse_request_form(raw_form)
        
        try:
            fuel_price = float(form_data.get('fuel_price', 0))
            driver_salary = float(form_data.get('driver_salary', 0))
            
            suppliers, buyers = DataProcessor.extract_entities(form_data)
            
            if not suppliers:
                raise ValueError("Додайте склад.")
            if not buyers:
                raise ValueError("Додайте клієнтів.")

            # Solve VRP
            solver = VRPSolver(fuel_price, driver_salary)
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
            
            # Save to DB
            new_calc = Calculation(
                total_cost=result['total_cost'], 
                total_km=result['total_km'], 
                result_json=json.dumps(result)
            )
            db.session.add(new_calc)
            db.session.commit()
            current_calc_id = new_calc.id
            
        except Exception as e:
            result = {'error': str(e)}
            
    return render_template('index.html', result=result, form=form_data, calc_id=current_calc_id, routes_json=routes_json)

@app.route('/history/<int:calc_id>')
def view_calculation(calc_id):
    calc = Calculation.query.get_or_404(calc_id)
    result = json.loads(calc.result_json)
    form_data = result.get('inputs', {})
    routes_json = json.dumps(result.get('routes', []))
    return render_template('index.html', result=result, form=form_data, calc_id=calc.id, routes_json=routes_json)

@app.route('/delete/<int:calc_id>', methods=['POST'])
def delete_calculation(calc_id):
    calc = Calculation.query.get_or_404(calc_id)
    db.session.delete(calc)
    db.session.commit()
    return redirect(url_for('history'))

@app.route('/history')
def history():
    return render_template('history.html', calculations=Calculation.query.order_by(Calculation.date.desc()).all())

@app.route('/export/<int:calc_id>')
def export_excel(calc_id):
    calc = Calculation.query.get_or_404(calc_id)
    data = json.loads(calc.result_json)
    
    output = ReportService.generate_excel(calc, data)
    filename = f"Route_{calc.id}.xlsx"
    
    return send_file(
        output, 
        as_attachment=True, 
        download_name=filename, 
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

if __name__ == '__main__':
    app.run(debug=True)