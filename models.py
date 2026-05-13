from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from flask_bcrypt import generate_password_hash

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='driver') # 'logistician' or 'driver'

class RouteAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    calculation_id = db.Column(db.Integer, db.ForeignKey('calculation.id'), nullable=False)
    route_index = db.Column(db.Integer, nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    calculation = db.relationship('Calculation', backref=db.backref('assignments', lazy=True))
    driver = db.relationship('User', backref=db.backref('assigned_routes', lazy=True))

class Calculation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.now)
    total_cost = db.Column(db.Float)
    total_km = db.Column(db.Float)
    result_json = db.Column(db.Text)

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Seed initial users
        if not User.query.first():
            logist = User(
                username='logist',
                name='Олександр (Логіст)',
                password_hash=generate_password_hash('1234').decode('utf-8'),
                role='logistician'
            )
            driver1 = User(
                username='driver1',
                name='Іван (Авто №1)',
                password_hash=generate_password_hash('1234').decode('utf-8'),
                role='driver'
            )
            driver2 = User(
                username='driver2',
                name='Василь (Авто №2)',
                password_hash=generate_password_hash('1234').decode('utf-8'),
                role='driver'
            )
            driver3 = User(
                username='driver3',
                name='Петро (Авто №3)',
                password_hash=generate_password_hash('1234').decode('utf-8'),
                role='driver'
            )
            db.session.add_all([logist, driver1, driver2, driver3])
            db.session.commit()
            print("Створено тестових користувачів.")
