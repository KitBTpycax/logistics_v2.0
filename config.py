import os
from dotenv import load_dotenv

# Завантажуємо змінні з файлу .env
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Беремо секретний ключ з .env, або ставимо запасний
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-fallback-key')
    
    # Налаштовуємо шлях до бази даних
    # Спочатку шукаємо DATABASE_URL (для PostgreSQL)
    # Якщо його немає, використовуємо локальний SQLite
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        SQLALCHEMY_DATABASE_URI = db_url
    else:
        db_name = os.getenv('DATABASE_NAME', 'logistic.db')
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(BASE_DIR, db_name)}'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False