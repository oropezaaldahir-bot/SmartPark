"""config.py · Ajustes de SmartPark. Todo se puede cambiar con variables de entorno."""
import os
from datetime import timedelta
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- Base de datos (cambia solo esta línea para usar otro motor SQL) ----
#   SQLite (por defecto):  sqlite:///smartpark.db
#   MySQL:                 mysql+pymysql://usuario:clave@localhost/smartpark       (pip install pymysql)
#   PostgreSQL:            postgresql+psycopg2://usuario:clave@localhost/smartpark (pip install psycopg2-binary)
#   SQL Server:            mssql+pyodbc://usuario:clave@servidor/smartpark?driver=ODBC+Driver+18+for+SQL+Server
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "smartpark.db"))

# Firma de las cookies de sesión. EN PRODUCCIÓN define SECRET_KEY con un valor largo y secreto.
SECRET_KEY = os.getenv("SECRET_KEY", "cambia-esto-en-produccion")

# ---- Administrador ----
# Para producción define ADMIN_PASS (o mejor, ADMIN_PASS_HASH con generate_password_hash de werkzeug).
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "smartpark2026")
ADMIN_PASS_HASH = os.getenv("ADMIN_PASS_HASH", "")
MAX_TRIES = 3
LOCK_SECONDS = 30

# ---- Negocio ----
TZ = ZoneInfo(os.getenv("APP_TZ", "America/Mexico_City"))
RATE = 15  # tarifa: $15 MXN por hora (o fracción)
TOL = timedelta(minutes=15)  # tolerancia de llegada y de salida tras pagar
HOLD = timedelta(minutes=10)  # tiempo que se aparta un cajón mientras se paga
SPOTS_PER_AREA = 8

# Con 0 no se cargan los vehículos DEMO la primera vez (úsalo con una base real).
SEED_DEMO = os.getenv("SEED_DEMO", "1") == "1"

# Con True muestra los avisos de "modo demostración" en la pasarela simulada.
DEMO_PAGOS = os.getenv("DEMO_PAGOS", "1") == "1"

AREAS = [
    {"id": "A", "n": "Área A", "c": "#2f6fed"},
    {"id": "B", "n": "Área B", "c": "#1f9d55"},
    {"id": "C", "n": "Área C", "c": "#d63b3b"},
    {"id": "D", "n": "Área D", "c": "#8e4ee0"},
    {"id": "E", "n": "Área E", "c": "#c9661a"},
    {"id": "F", "n": "Área F", "c": "#ec4899"},
]

