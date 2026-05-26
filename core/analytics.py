from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, timezone, timedelta
from typing import Any, Dict, Iterable, Optional
import pandas as pd
import numpy as np

TZ = timezone.utc

LIKERT = None

def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).replace('Z', '+00:00')
        return datetime.fromisoformat(s)
    except Exception:
        return None

def hours_since(dt: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds() / 3600)

def disconnection_risk(hours: Optional[float]) -> str:
    if hours is None:
        return 'Alto'
    if hours <= 24:
        return 'Bajo'
    if hours <= 72:
        return 'Medio'
    return 'Alto'

def business_days_between(start: date, end: date) -> int:
    if end < start:
        return 0
    days = pd.date_range(start=start, end=end, freq='B')
    return len(days)

def expected_hours(course_start: date, analysis_date: date, daily_hours: float, only_business_days: bool) -> float:
    if only_business_days:
        days = business_days_between(course_start, analysis_date)
    else:
        days = (analysis_date - course_start).days + 1 if analysis_date >= course_start else 0
    return max(0.0, days * daily_hours)

def normalize_enrollments(enrollments: list[dict], analysis_dt: datetime, course_start: date, daily_hours: float, only_business_days: bool) -> pd.DataFrame:
    rows = []
    exp_h = expected_hours(course_start, analysis_dt.date(), daily_hours, only_business_days)
    for e in enrollments:
        user = e.get('user') or {}
        last_dt = parse_dt(e.get('last_activity_at'))
        hs = hours_since(last_dt, analysis_dt)
        total_secs = e.get('total_activity_time') or 0
        total_hours = round(float(total_secs) / 3600, 2) if total_secs else 0.0
        deficit = round(max(0.0, exp_h - total_hours), 2)
        compliance = 'Cumple' if total_hours >= exp_h else ('Cerca' if total_hours >= exp_h * 0.8 else 'No cumple')
        rows.append({
            'user_id': user.get('id') or e.get('user_id'),
            'estudiante': user.get('sortable_name') or user.get('name') or 'Sin nombre',
            'nombre': user.get('name') or 'Sin nombre',
            'correo': user.get('login_id') or user.get('email') or '',
            'section_id': e.get('course_section_id'),
            'ultima_actividad': last_dt,
            'horas_sin_actividad': None if hs is None else round(hs, 1),
            'riesgo_desconexion': disconnection_risk(hs),
            'tiempo_total_horas': total_hours,
            'horas_esperadas': round(exp_h, 2),
            'deficit_horas': deficit,
            'cumplimiento_horas': compliance,
        })
    return pd.DataFrame(rows)

def normalize_assignments(assignments: list[dict]) -> pd.DataFrame:
    rows = []
    for a in assignments:
        if a.get('published') is False:
            continue
        rows.append({
            'assignment_id': a.get('id'),
            'actividad': a.get('name'),
            'puntos': a.get('points_possible') or 0,
            'fecha_entrega': parse_dt(a.get('due_at')),
            'published': a.get('published'),
            'omit_from_final_grade': a.get('omit_from_final_grade', False),
        })
    return pd.DataFrame(rows)

def normalize_submissions(submissions: list[dict]) -> pd.DataFrame:
    """Normaliza entregas de Canvas.

    Canvas puede devolver /students/submissions de dos formas:
    1) Lista plana: cada elemento es una entrega.
    2) Lista agrupada por estudiante: cada elemento tiene user_id y una lista interna
       llamada submissions.

    Algunas instancias de Canvas devuelven la forma agrupada aunque se solicite
    grouped=false. Por eso aquí se aplana automáticamente antes de construir
    la tabla de entregas.
    """
    rows = []

    def add_row(s: dict, fallback_user_id=None):
        a = s.get('assignment') or {}
        rows.append({
            'user_id': s.get('user_id') or fallback_user_id,
            'assignment_id': s.get('assignment_id') or a.get('id'),
            'actividad': a.get('name'),
            'fecha_entrega': parse_dt(a.get('due_at')),
            'submitted_at': parse_dt(s.get('submitted_at')),
            'workflow_state': s.get('workflow_state'),
            'missing': bool(s.get('missing')),
            'late': bool(s.get('late')),
            'score': s.get('score'),
            'puntos': a.get('points_possible') or 0,
            'excused': bool(s.get('excused')),
        })

    for item in submissions or []:
        if not isinstance(item, dict):
            continue

        # Respuesta agrupada por estudiante:
        # {'user_id': 123, 'submissions': [{...}, {...}]}
        if isinstance(item.get('submissions'), list):
            fallback_user_id = item.get('user_id')
            for sub in item.get('submissions') or []:
                if isinstance(sub, dict):
                    add_row(sub, fallback_user_id=fallback_user_id)
            continue

        # Respuesta plana: cada item ya es una entrega.
        add_row(item)

    return pd.DataFrame(rows)

def build_student_summary(enroll_df: pd.DataFrame, sub_df: pd.DataFrame, analysis_dt: datetime) -> pd.DataFrame:
    if enroll_df.empty:
        return enroll_df
    if sub_df.empty:
        base = enroll_df.copy()
        for col in ['actividades_total','entregadas','pendientes','atrasadas','porcentaje_avance','promedio_score']:
            base[col] = 0
        return score_risk(base)
    sub = sub_df.copy()
    submitted = sub['submitted_at'].notna() | sub['workflow_state'].isin(['submitted', 'graded'])
    sub['entregada_calc'] = submitted & ~sub['excused']
    due_past = sub['fecha_entrega'].notna() & (sub['fecha_entrega'] < analysis_dt)
    sub['pendiente_calc'] = ~sub['entregada_calc'] & ~sub['excused']
    sub['atrasada_calc'] = sub['pendiente_calc'] & (sub['late'] | sub['missing'] | due_past)
    grp = sub.groupby('user_id').agg(
        actividades_total=('assignment_id', 'nunique'),
        entregadas=('entregada_calc', 'sum'),
        pendientes=('pendiente_calc', 'sum'),
        atrasadas=('atrasada_calc', 'sum'),
        promedio_score=('score', 'mean')
    ).reset_index()
    grp['porcentaje_avance'] = np.where(grp['actividades_total'] > 0, (grp['entregadas'] / grp['actividades_total'] * 100).round(1), 0)
    base = enroll_df.merge(grp, on='user_id', how='left')
    fill_cols = ['actividades_total','entregadas','pendientes','atrasadas','porcentaje_avance']
    base[fill_cols] = base[fill_cols].fillna(0)
    base['promedio_score'] = base['promedio_score'].fillna(0).round(2)
    return score_risk(base)

def score_risk(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    def points(row):
        p = 0
        r = row.get('riesgo_desconexion')
        if r == 'Medio': p += 30
        if r == 'Alto': p += 50
        if row.get('cumplimiento_horas') == 'Cerca': p += 10
        if row.get('cumplimiento_horas') == 'No cumple': p += 20
        if row.get('atrasadas', 0) >= 1: p += 20
        if row.get('pendientes', 0) >= 2: p += 15
        if row.get('porcentaje_avance', 100) < 60: p += 20
        return min(100, int(p))
    out['puntaje_riesgo'] = out.apply(points, axis=1)
    out['riesgo_integral'] = pd.cut(out['puntaje_riesgo'], bins=[-1, 29, 59, 100], labels=['Bajo','Medio','Alto']).astype(str)
    out['segmento_ave'] = out.apply(segment_student, axis=1)
    out['accion_recomendada'] = out.apply(recommended_action, axis=1)
    return out.sort_values(['puntaje_riesgo','horas_sin_actividad'], ascending=[False, False])

def segment_student(row) -> str:
    if row.get('riesgo_desconexion') == 'Alto' and row.get('pendientes', 0) >= 2:
        return 'Intervención inmediata'
    if row.get('horas_sin_actividad') is None:
        return 'Sin registro de actividad'
    if row.get('atrasadas', 0) >= 1:
        return 'Entrega vencida'
    if row.get('cumplimiento_horas') == 'No cumple':
        return 'Baja conexión'
    if row.get('porcentaje_avance', 0) < 60:
        return 'Bajo avance'
    if row.get('riesgo_integral') == 'Bajo':
        return 'Activo estable'
    return 'Observación preventiva'

def recommended_action(row) -> str:
    segment = row.get('segmento_ave', '')
    if segment == 'Intervención inmediata':
        return 'Contactar hoy y registrar seguimiento'
    if segment == 'Sin registro de actividad':
        return 'Verificar ingreso inicial y contactar'
    if segment == 'Entrega vencida':
        return 'Recordar entregas vencidas y definir plan'
    if segment == 'Baja conexión':
        return 'Orientar cumplimiento de horas mínimas'
    if segment == 'Bajo avance':
        return 'Revisar avance y prioridades del módulo'
    if row.get('riesgo_integral') == 'Medio':
        return 'Contacto preventivo'
    return 'Monitoreo regular'

# ===== PRO 2.1: Analítica por módulos Canvas =====
def normalize_modules(modules: list[dict]) -> pd.DataFrame:
    rows = []
    for m in modules or []:
        rows.append({
            'module_id': m.get('id'),
            'modulo': m.get('name'),
            'posicion_modulo': m.get('position'),
            'estado_modulo': m.get('state'),
            'completado_en': parse_dt(m.get('completed_at')),
            'items_count': m.get('items_count'),
            'requirement_type': m.get('requirement_type'),
            'published': m.get('published', True),
        })
    return pd.DataFrame(rows)

def normalize_module_items(modules: list[dict]) -> pd.DataFrame:
    rows = []
    for m in modules or []:
        for item in m.get('items') or []:
            details = item.get('content_details') or {}
            req = item.get('completion_requirement') or {}
            rows.append({
                'module_id': m.get('id'),
                'modulo': m.get('name'),
                'posicion_modulo': m.get('position'),
                'module_item_id': item.get('id'),
                'posicion_item': item.get('position'),
                'titulo_item': item.get('title'),
                'tipo_item': item.get('type'),
                'content_id': item.get('content_id'),
                'html_url': item.get('html_url'),
                'published': item.get('published', True),
                'puntos': details.get('points_possible'),
                'fecha_entrega': parse_dt(details.get('due_at')),
                'locked_for_user': details.get('locked_for_user'),
                'tipo_requisito': req.get('type'),
                'min_score': req.get('min_score'),
                'min_percentage': req.get('min_percentage'),
                'requisito_completado': req.get('completed'),
                'es_entregable': item.get('type') in ['Assignment','Quiz','Discussion'] or req.get('type') in ['must_submit','min_score','min_percentage','must_contribute'],
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(['posicion_modulo','posicion_item'])
    return df

def build_module_completion_matrix(enroll_df: pd.DataFrame, module_items_df: pd.DataFrame, sub_df: pd.DataFrame) -> pd.DataFrame:
    """Cruza estudiantes vs entregables de módulos.

    Usa `content_id` de los ítems tipo Assignment/Quiz/Discussion para empatar con
    `assignment_id` de submissions. Para recursos no calificables, conserva el ítem
    como referencia, pero su estado queda como "No aplica" si no hay submission.
    """
    if enroll_df.empty or module_items_df.empty:
        return pd.DataFrame()
    deliverables = module_items_df[module_items_df['es_entregable'].fillna(False)].copy()
    if deliverables.empty:
        deliverables = module_items_df.copy()
    sub = sub_df.copy() if sub_df is not None else pd.DataFrame()
    rows = []
    for _, stu in enroll_df.iterrows():
        uid = stu.get('user_id')
        stu_sub = sub[sub['user_id'].eq(uid)] if not sub.empty and 'user_id' in sub.columns else pd.DataFrame()
        for _, item in deliverables.iterrows():
            content_id = item.get('content_id')
            matched = pd.DataFrame()
            if not stu_sub.empty and pd.notna(content_id):
                matched = stu_sub[stu_sub['assignment_id'].eq(content_id)]
            if not matched.empty:
                s = matched.iloc[0]
                entregada = bool(pd.notna(s.get('submitted_at')) or s.get('workflow_state') in ['submitted','graded'])
                pendiente = not entregada and not bool(s.get('excused'))
                atrasada = bool(s.get('late')) or bool(s.get('missing'))
                estado = 'Entregado' if entregada else ('Atrasado' if atrasada else 'Pendiente')
                score = s.get('score')
                submitted_at = s.get('submitted_at')
            else:
                entregada = False
                pendiente = True if item.get('es_entregable') else False
                atrasada = False
                estado = 'Pendiente' if item.get('es_entregable') else 'No aplica'
                score = None
                submitted_at = None
            rows.append({
                'user_id': uid,
                'estudiante': stu.get('estudiante'),
                'correo': stu.get('correo'),
                'module_id': item.get('module_id'),
                'modulo': item.get('modulo'),
                'module_item_id': item.get('module_item_id'),
                'entregable': item.get('titulo_item'),
                'tipo_item': item.get('tipo_item'),
                'content_id': content_id,
                'fecha_entrega': item.get('fecha_entrega'),
                'estado': estado,
                'entregado': entregada,
                'pendiente': pendiente,
                'atrasado': atrasada,
                'score': score,
                'submitted_at': submitted_at,
                'html_url': item.get('html_url'),
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(['modulo','entregable','estudiante'])
    return out
