import sqlite3
from pathlib import Path
import pandas as pd
from datetime import datetime

DB = Path('ave_canvas_analytics.sqlite')

def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS historial (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT, course_id TEXT, course_name TEXT, user_id TEXT, nombre TEXT, correo TEXT,
        riesgo_integral TEXT, puntaje_riesgo INTEGER, horas_sin_actividad REAL,
        pendientes INTEGER, atrasadas INTEGER, avance REAL, segmento_ave TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS bitacora (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_registro TEXT, course_id TEXT, user_id TEXT, estudiante TEXT, responsable TEXT,
        medio TEXT, motivo TEXT, resultado TEXT, proxima_accion TEXT, fecha_seguimiento TEXT, observaciones TEXT
    )''')
    con.commit(); con.close()


def save_history(summary, course_id, course_name):
    if summary is None or summary.empty: return
    init_db()
    df = summary.copy()
    df['fecha'] = datetime.now().isoformat(timespec='seconds')
    df['course_id'] = str(course_id)
    df['course_name'] = course_name
    cols = ['fecha','course_id','course_name','user_id','nombre','correo','riesgo_integral','puntaje_riesgo','horas_sin_actividad','pendientes','atrasadas','avance_%','segmento_ave']
    out = df[[c for c in cols if c in df.columns]].rename(columns={'avance_%':'avance'})
    con = sqlite3.connect(DB); out.to_sql('historial', con, if_exists='append', index=False); con.close()


def read_history(course_id=None):
    init_db(); con = sqlite3.connect(DB)
    q = 'SELECT * FROM historial'
    params = []
    if course_id:
        q += ' WHERE course_id=?'; params.append(str(course_id))
    q += ' ORDER BY fecha DESC'
    df = pd.read_sql_query(q, con, params=params); con.close(); return df


def save_log(course_id, user_id, estudiante, responsable, medio, motivo, resultado, proxima_accion, fecha_seguimiento, observaciones):
    init_db(); con = sqlite3.connect(DB)
    pd.DataFrame([{
        'fecha_registro': datetime.now().isoformat(timespec='seconds'), 'course_id': str(course_id), 'user_id': str(user_id),
        'estudiante': estudiante, 'responsable': responsable, 'medio': medio, 'motivo': motivo, 'resultado': resultado,
        'proxima_accion': proxima_accion, 'fecha_seguimiento': str(fecha_seguimiento), 'observaciones': observaciones
    }]).to_sql('bitacora', con, if_exists='append', index=False)
    con.close()


def read_log(course_id=None):
    init_db(); con = sqlite3.connect(DB)
    q='SELECT * FROM bitacora'; params=[]
    if course_id:
        q+=' WHERE course_id=?'; params.append(str(course_id))
    q+=' ORDER BY fecha_registro DESC'
    df=pd.read_sql_query(q, con, params=params); con.close(); return df
