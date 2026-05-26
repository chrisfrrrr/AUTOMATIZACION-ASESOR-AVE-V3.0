import math
import pandas as pd
from datetime import datetime, timezone
from dateutil import parser


def parse_dt(x):
    if not x or pd.isna(x):
        return None
    try:
        dt = parser.parse(str(x))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def hours_since(dt_value, cutoff=None):
    dt = parse_dt(dt_value)
    if dt is None:
        return None
    cutoff_dt = parse_dt(cutoff) or datetime.now(timezone.utc)
    return round(max((cutoff_dt - dt).total_seconds() / 3600, 0), 1)


def risk_disconnect(h):
    if h is None:
        return 'Alto'
    if h <= 24:
        return 'Bajo'
    if h <= 72:
        return 'Medio'
    return 'Alto'


def expected_hours(start_date, cutoff_date, daily_goal=2.0, business_days=False):
    s = pd.to_datetime(start_date).date()
    c = pd.to_datetime(cutoff_date).date()
    if c < s:
        return 0.0
    days = pd.date_range(s, c, freq='D')
    if business_days:
        days = [d for d in days if d.weekday() < 5]
    return round(len(days) * float(daily_goal), 2)


def normalize_students(enrollments, cutoff_date):
    rows = []
    for e in enrollments:
        u = e.get('user') or {}
        total_seconds = e.get('total_activity_time') or 0
        rows.append({
            'user_id': u.get('id') or e.get('user_id'),
            'nombre': u.get('sortable_name') or u.get('name'),
            'nombre_mostrar': u.get('name'),
            'correo': u.get('login_id') or u.get('email'),
            'section_id': e.get('course_section_id'),
            'ultima_actividad': e.get('last_activity_at'),
            'horas_sin_actividad': hours_since(e.get('last_activity_at'), cutoff_date),
            'horas_totales': round(float(total_seconds) / 3600, 2),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['riesgo_desconexion'] = df['horas_sin_actividad'].apply(risk_disconnect)
    return df


def normalize_assignments(assignments):
    rows = []
    for a in assignments:
        rows.append({
            'assignment_id': a.get('id'),
            'actividad': a.get('name'),
            'fecha_entrega': a.get('due_at'),
            'puntos': a.get('points_possible') or 0,
            'published': a.get('published'),
            'submission_types': ', '.join(a.get('submission_types') or []),
            'omit_from_final_grade': a.get('omit_from_final_grade'),
        })
    return pd.DataFrame(rows)


def normalize_submissions(submissions):
    rows = []
    for s in submissions:
        a = s.get('assignment') or {}
        uid = s.get('user_id') or s.get('_group_user_id')
        missing = bool(s.get('missing'))
        late = bool(s.get('late'))
        submitted = s.get('submitted_at')
        state = s.get('workflow_state')
        delivered = bool(submitted) or state in ('submitted', 'graded')
        rows.append({
            'user_id': uid,
            'assignment_id': s.get('assignment_id') or a.get('id'),
            'actividad': a.get('name'),
            'fecha_entrega': a.get('due_at'),
            'submitted_at': submitted,
            'workflow_state': state,
            'missing': missing,
            'late': late,
            'score': s.get('score'),
            'puntos': a.get('points_possible') or 0,
            'estado_entrega': 'Atrasado' if late or missing else ('Entregado' if delivered else 'Pendiente')
        })
    return pd.DataFrame(rows)


def build_summary(students_df, submissions_df, start_date, cutoff_date, daily_goal=2.0, business_days=False):
    if students_df.empty:
        return students_df.copy()
    expected = expected_hours(start_date, cutoff_date, daily_goal, business_days)
    summary = students_df.copy()
    if submissions_df is not None and not submissions_df.empty:
        g = submissions_df.groupby('user_id').agg(
            actividades_total=('assignment_id', 'nunique'),
            entregadas=('estado_entrega', lambda x: int((x == 'Entregado').sum())),
            pendientes=('estado_entrega', lambda x: int((x == 'Pendiente').sum())),
            atrasadas=('estado_entrega', lambda x: int((x == 'Atrasado').sum())),
        ).reset_index()
        summary = summary.merge(g, on='user_id', how='left')
    for col in ['actividades_total','entregadas','pendientes','atrasadas']:
        summary[col] = summary.get(col, 0).fillna(0).astype(int)
    summary['avance_%'] = summary.apply(lambda r: round((r['entregadas'] / r['actividades_total'] * 100), 1) if r['actividades_total'] else 0, axis=1)
    summary['horas_esperadas'] = expected
    summary['deficit_horas'] = (summary['horas_esperadas'] - summary['horas_totales']).clip(lower=0).round(2)
    def score(r):
        pts = 0
        h = r['horas_sin_actividad']
        if pd.isna(h): pts += 50
        elif h > 72: pts += 50
        elif h > 24: pts += 30
        if r['deficit_horas'] > 2: pts += 20
        if r['pendientes'] > 0: pts += min(20, r['pendientes'] * 5)
        if r['atrasadas'] > 0: pts += min(25, r['atrasadas'] * 10)
        if r['avance_%'] < 50 and r['actividades_total'] > 0: pts += 10
        return min(100, int(pts))
    summary['puntaje_riesgo'] = summary.apply(score, axis=1)
    summary['riesgo_integral'] = summary['puntaje_riesgo'].apply(lambda x: 'Alto' if x >= 60 else ('Medio' if x >= 30 else 'Bajo'))
    def segment(r):
        if pd.isna(r['horas_sin_actividad']): return 'Sin registro de actividad'
        if r['riesgo_integral'] == 'Alto': return 'Intervención inmediata'
        if r['atrasadas'] > 0: return 'Entrega vencida'
        if r['pendientes'] > 0: return 'Bajo avance'
        if r['riesgo_desconexion'] == 'Medio': return 'Baja conexión'
        if r['puntaje_riesgo'] > 0: return 'Observación preventiva'
        return 'Activo estable'
    summary['segmento_ave'] = summary.apply(segment, axis=1)
    return summary.sort_values(['puntaje_riesgo','horas_sin_actividad','pendientes','atrasadas'], ascending=[False,False,False,False])


def modules_tables(modules):
    module_rows, item_rows = [], []
    for m in modules:
        module_rows.append({'module_id': m.get('id'), 'modulo': m.get('name'), 'position': m.get('position'), 'state': m.get('state')})
        for it in m.get('items') or []:
            item_rows.append({
                'module_id': m.get('id'), 'modulo': m.get('name'), 'item_id': it.get('id'), 'titulo_item': it.get('title'),
                'tipo': it.get('type'), 'content_id': it.get('content_id'), 'position': it.get('position'),
                'completion_requirement': str(it.get('completion_requirement') or '')
            })
    return pd.DataFrame(module_rows), pd.DataFrame(item_rows)


def module_matrix(students_df, items_df, submissions_df):
    if students_df.empty or items_df.empty:
        return pd.DataFrame()
    deliverables = items_df[items_df['tipo'].isin(['Assignment','Quiz','Discussion'])].copy()
    if deliverables.empty:
        return pd.DataFrame()
    sub = submissions_df.copy() if submissions_df is not None else pd.DataFrame()
    rows = []
    for _, st in students_df.iterrows():
        user_id = st['user_id']
        for _, it in deliverables.iterrows():
            estado = 'No aplica'
            if not sub.empty and pd.notna(it.get('content_id')):
                matches = sub[(sub['user_id'].astype(str)==str(user_id)) & (sub['assignment_id'].astype(str)==str(it.get('content_id')))]
                if not matches.empty:
                    estado = matches.iloc[0].get('estado_entrega') or 'Pendiente'
                else:
                    estado = 'Pendiente'
            rows.append({'user_id': user_id, 'estudiante': st.get('nombre_mostrar') or st.get('nombre'), 'correo': st.get('correo'), 'modulo': it.get('modulo'), 'entregable': it.get('titulo_item'), 'tipo': it.get('tipo'), 'estado': estado})
    return pd.DataFrame(rows)
