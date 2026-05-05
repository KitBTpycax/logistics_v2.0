from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

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
