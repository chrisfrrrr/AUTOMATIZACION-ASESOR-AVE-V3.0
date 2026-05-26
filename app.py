import os
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import date
from core.canvas_client import CanvasClient, CanvasError
from core.analytics import normalize_students, normalize_assignments, normalize_submissions, build_summary, modules_tables, module_matrix
from core.storage import save_history, read_history, save_log, read_log, init_db
from core.reports import excel_bytes, pdf_bytes, DEV

st.set_page_config(page_title='AVE Canvas Analytics Pro 2.1', page_icon='assets/app_icon.ico', layout='wide')
init_db()

st.markdown('''<style>
[data-testid="stSidebar"]{background:#f2f5f9}.main .block-container{padding-top:2rem;max-width:1250px}
.metric-card{background:white;border:1px solid #e6e9ef;border-radius:18px;padding:18px;box-shadow:0 4px 16px rgba(20,30,80,.05)}
.title{font-size:2.1rem;font-weight:800;color:#1B2A7A}.sub{color:#4c566a;font-size:1.05rem}.danger{color:#ff4b4b;font-weight:700}
</style>''', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    if os.path.exists('assets/logo_ave.png'):
        st.image('assets/logo_ave.png', use_container_width=True)
    canvas_url = st.text_input('URL Canvas', value=st.session_state.get('canvas_url','https://uvg.instructure.com'))
    token = st.text_input('Token de acceso', type='password', value=st.session_state.get('token',''))
    generated_by = st.text_input('Nombre de quien genera el informe', value=st.session_state.get('generated_by',''))
    st.divider()
    st.subheader('Parámetros académicos')
    daily_goal = st.number_input('Meta mínima diaria de conexión (horas)', min_value=0.0, max_value=12.0, value=2.0, step=0.5)
    start_date = st.date_input('Fecha de inicio del curso', value=date.today())
    business_days = st.checkbox('Calcular meta solo con días hábiles', value=False)
    cutoff_date = st.date_input('Fecha de corte del análisis', value=date.today())
    st.divider()
    if st.button('Probar conexión / cargar cursos', use_container_width=True, type='primary'):
        try:
            client=CanvasClient(canvas_url, token)
            me=client.test(); courses=client.courses()
            st.session_state.update({'canvas_url':canvas_url,'token':token,'generated_by':generated_by,'me':me,'courses':courses})
            st.success(f"Conectado como {me.get('name')}")
        except Exception as e:
            st.error(str(e))
    st.caption(f'Desarrollador: {DEV}')

st.markdown('<div class="title">Herramienta de análisis y seguimiento AVE - Canvas Analytics Pro 2.1</div>', unsafe_allow_html=True)
st.markdown('<div class="sub">Dashboard ejecutivo, módulos, entregables, mensajería Canvas, bitácora y reportes institucionales.</div>', unsafe_allow_html=True)

if 'courses' not in st.session_state:
    st.info('Ingresa URL y token en la barra lateral, luego presiona “Probar conexión / cargar cursos”.')
    st.stop()

courses = st.session_state.get('courses', [])
course_options={f"{c.get('name','Sin nombre')} | ID {c.get('id')}": c for c in courses if c.get('id')}
selected_course_key=st.selectbox('Seleccione curso', list(course_options.keys()))
course=course_options[selected_course_key]
course_id=course['id']; course_name=course.get('name','')
client=CanvasClient(st.session_state.get('canvas_url', canvas_url), st.session_state.get('token', token))

# Sections
try:
    sections=client.sections(course_id)
except Exception:
    sections=[]
section_options={'Todas las secciones': None}
for s in sections:
    section_options[f"{s.get('name')} | ID {s.get('id')}"]=s.get('id')
selected_section_key=st.selectbox('Seleccione sección', list(section_options.keys()))
section_id=section_options[selected_section_key]

c1,c2=st.columns([1,1])
with c1:
    run=st.button('Generar análisis Pro 2.1', type='primary', use_container_width=True)
with c2:
    if st.button('Limpiar resultados', use_container_width=True):
        for k in ['summary','students','submissions','assignments','hist','modules','module_items','module_matrix','staff']:
            st.session_state.pop(k, None)
        st.rerun()

if run:
    prog=st.progress(0); msg=st.empty()
    try:
        msg.write('Extrayendo estudiantes...'); prog.progress(10)
        enroll=client.students(course_id, section_id)
        students_df=normalize_students(enroll, cutoff_date)
        student_ids=students_df['user_id'].dropna().astype(str).tolist() if not students_df.empty else []
        msg.write('Extrayendo actividades...'); prog.progress(25)
        assignments=client.assignments(course_id); assignments_df=normalize_assignments(assignments)
        msg.write('Extrayendo entregas por bloques...'); prog.progress(45)
        subs=client.submissions_for_students(course_id, student_ids, chunk_size=20); submissions_df=normalize_submissions(subs)
        msg.write('Leyendo módulos e ítems...'); prog.progress(65)
        mods=client.modules_with_items(course_id); modules_df, module_items_df=modules_tables(mods)
        matrix_df=module_matrix(students_df, module_items_df, submissions_df)
        msg.write('Calculando riesgo integral...'); prog.progress(80)
        summary=build_summary(students_df, submissions_df, start_date, cutoff_date, daily_goal, business_days)
        staff_df=normalize_students(client.staff(course_id), cutoff_date)
        hist=read_history(course_id)
        save_history(summary, course_id, course_name)
        st.session_state.update({'students':students_df,'assignments':assignments_df,'submissions':submissions_df,'summary':summary,'hist':hist,'modules':modules_df,'module_items':module_items_df,'module_matrix':matrix_df,'staff':staff_df})
        prog.progress(100); msg.success('Análisis completado correctamente.')
    except Exception as e:
        st.error(f'Ocurrió un error durante el análisis: {e}')

summary=st.session_state.get('summary', pd.DataFrame())
students_df=st.session_state.get('students', pd.DataFrame())
submissions_df=st.session_state.get('submissions', pd.DataFrame())
modules_df=st.session_state.get('modules', pd.DataFrame())
module_items_df=st.session_state.get('module_items', pd.DataFrame())
matrix_df=st.session_state.get('module_matrix', pd.DataFrame())
staff_df=st.session_state.get('staff', pd.DataFrame())
history_df=read_history(course_id)
bitacora_df=read_log(course_id)

student_options={}
if not summary.empty:
    for _, r in summary.iterrows():
        student_options[f"{r.get('nombre_mostrar') or r.get('nombre')} | {r.get('correo')} | ID {r.get('user_id')}"]=r.get('user_id')

tabs=st.tabs(['Dashboard','Estudiantes','Entregas','Módulos','Mensajes Canvas','Bitácora','Historial','Reportes'])

with tabs[0]:
    st.header('Resumen ejecutivo')
    if summary.empty:
        st.warning('Aún no hay análisis generado.')
    else:
        total=len(summary); bajo=(summary['riesgo_integral']=='Bajo').sum(); medio=(summary['riesgo_integral']=='Medio').sum(); alto=(summary['riesgo_integral']=='Alto').sum()
        m1,m2,m3,m4,m5=st.columns(5)
        m1.metric('Estudiantes', total); m2.metric('Riesgo bajo', bajo); m3.metric('Riesgo medio', medio); m4.metric('Riesgo alto', alto); m5.metric('Pendientes', int(summary['pendientes'].sum()))
        col1,col2=st.columns(2)
        with col1:
            fig=px.pie(summary, names='riesgo_integral', title='Distribución de riesgo integral')
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            seg=summary['segmento_ave'].value_counts().reset_index(); seg.columns=['segmento','cantidad']
            fig=px.bar(seg, x='segmento', y='cantidad', title='Segmentación AVE')
            st.plotly_chart(fig, use_container_width=True)
        st.subheader('Estudiantes sugeridos para contactar hoy')
        contact=summary[summary['riesgo_integral'].isin(['Alto','Medio'])]
        st.dataframe(contact[['nombre','correo','riesgo_integral','segmento_ave','puntaje_riesgo','horas_sin_actividad','pendientes','atrasadas']], use_container_width=True, hide_index=True)

with tabs[1]:
    st.header('Estudiantes')
    st.dataframe(summary if not summary.empty else students_df, use_container_width=True, hide_index=True)

with tabs[2]:
    st.header('Entregas')
    st.dataframe(submissions_df, use_container_width=True, hide_index=True)

with tabs[3]:
    st.header('Vista por módulos y entregables')
    st.caption('La vista replica la lógica de Canvas: módulo → ítems → entregables. Permite revisar qué realizó o qué falta por estudiante.')
    if modules_df.empty:
        st.warning('Genera el análisis para cargar módulos.')
    else:
        colA,colB=st.columns([1,1])
        with colA:
            mod_filter=st.selectbox('Filtrar módulo', ['Todos'] + modules_df['modulo'].dropna().astype(str).tolist())
        with colB:
            state_filter=st.selectbox('Filtrar estado matriz', ['Todos','Entregado','Pendiente','Atrasado','No aplica'])
        items_view=module_items_df.copy()
        if mod_filter!='Todos': items_view=items_view[items_view['modulo']==mod_filter]
        st.subheader('Ítems por módulo')
        st.dataframe(items_view, use_container_width=True, hide_index=True)
        st.subheader('Matriz estudiante vs entregable')
        mat=matrix_df.copy()
        if mod_filter!='Todos': mat=mat[mat['modulo']==mod_filter]
        if state_filter!='Todos': mat=mat[mat['estado']==state_filter]
        st.dataframe(mat, use_container_width=True, hide_index=True)
        if student_options:
            student_key_mod=st.selectbox('Seleccione estudiante para revisar pendientes por módulo', list(student_options.keys()), key='mod_student')
            uid=student_options[student_key_mod]
            indiv=matrix_df[matrix_df['user_id'].astype(str)==str(uid)]
            st.dataframe(indiv, use_container_width=True, hide_index=True)
            pendientes=indiv[indiv['estado'].isin(['Pendiente','Atrasado'])]
            st.info(f'Pendientes/atrasados detectados: {len(pendientes)}')

with tabs[4]:
    st.header('Mensajes Canvas')
    st.warning('Para seguridad, prueba primero con profesores/TA. Para estudiantes, se recomienda conversación privada, no grupal.')
    if summary.empty:
        st.info('Genera el análisis antes de enviar mensajes.')
    else:
        modo=st.radio('Destinatarios', ['Modo prueba: profesores/TA del curso','Estudiantes en riesgo alto','Estudiantes en riesgo medio','Estudiantes alto + medio','Selección manual'], horizontal=False)
        if modo.startswith('Modo prueba'):
            targets=staff_df.copy()
        elif modo=='Estudiantes en riesgo alto': targets=summary[summary['riesgo_integral']=='Alto']
        elif modo=='Estudiantes en riesgo medio': targets=summary[summary['riesgo_integral']=='Medio']
        elif modo=='Estudiantes alto + medio': targets=summary[summary['riesgo_integral'].isin(['Alto','Medio'])]
        else:
            selected=st.multiselect('Seleccione estudiantes', list(student_options.keys()))
            ids=[student_options[x] for x in selected]
            targets=summary[summary['user_id'].astype(str).isin([str(i) for i in ids])]
        st.write(f'Destinatarios seleccionados: **{len(targets)}**')
        st.dataframe(targets[['user_id','nombre','correo','riesgo_integral','segmento_ave']] if not targets.empty and 'riesgo_integral' in targets.columns else targets, use_container_width=True, hide_index=True)
        subject=st.text_input('Asunto del mensaje Canvas', value=f'Seguimiento académico AVE - {course_name}')
        default_body='Hola, espero que estés bien. Al revisar el seguimiento del curso, se identificó que necesitas reforzar tu avance y conexión en Canvas. Te recomiendo ingresar hoy, revisar los módulos activos y priorizar las actividades pendientes. Estoy pendiente para apoyarte si tienes alguna dificultad.'
        body=st.text_area('Mensaje', value=default_body, height=180)
        group=st.checkbox('Enviar como conversación grupal', value=False, help='Si se marca, los destinatarios pueden ver la conversación grupal. Para estudiantes se recomienda dejarlo desmarcado.')
        confirm=st.checkbox('Confirmo que deseo enviar este mensaje desde Canvas')
        if st.button('Enviar mensaje por Canvas', type='primary', use_container_width=True):
            if not confirm:
                st.error('Debes confirmar el envío.')
            elif targets.empty:
                st.error('No hay destinatarios seleccionados.')
            else:
                ids=targets['user_id'].dropna().astype(str).tolist()
                try:
                    res=client.send_conversation(course_id, ids, subject, body, group=group, chunk_size=20)
                    ok=sum(1 for r in res if r.get('ok')); fail=[r for r in res if not r.get('ok')]
                    st.success(f'Proceso terminado. Bloques enviados correctamente: {ok}. Errores: {len(fail)}')
                    if fail: st.dataframe(pd.DataFrame(fail), use_container_width=True)
                except Exception as e:
                    st.error(f'No se pudo enviar el mensaje por Canvas: {e}')

with tabs[5]:
    st.header('Bitácora de intervención')
    if student_options:
        k=st.selectbox('Estudiante', list(student_options.keys()), key='log_student')
        uid=student_options[k]
        col1,col2=st.columns(2)
        medio=col1.selectbox('Medio', ['Canvas','Correo','Llamada','WhatsApp institucional','Otro'])
        motivo=col2.selectbox('Motivo', ['Riesgo alto','Riesgo medio','Pendiente de entrega','Baja conexión','Bajo avance','Otro'])
        resultado=st.selectbox('Resultado', ['Pendiente','Respondió','No respondió','Se comprometió','Requiere apoyo','Caso escalado'])
        prox=st.text_input('Próxima acción')
        fseg=st.date_input('Fecha de seguimiento', value=date.today(), key='fseg')
        obs=st.text_area('Observaciones')
        if st.button('Guardar bitácora'):
            save_log(course_id, uid, k, st.session_state.get('generated_by',''), medio, motivo, resultado, prox, fseg, obs)
            st.success('Registro guardado.')
    st.dataframe(read_log(course_id), use_container_width=True, hide_index=True)

with tabs[6]:
    st.header('Historial')
    st.dataframe(history_df, use_container_width=True, hide_index=True)

with tabs[7]:
    st.header('Reportes y exportables')
    if summary.empty:
        st.warning('Genera el análisis antes de exportar.')
    else:
        xlsx=excel_bytes(summary, submissions_df, history_df, modules_df, module_items_df, matrix_df, read_log(course_id))
        st.download_button('Descargar Excel Pro completo', xlsx, file_name='AVE_Canvas_Analytics_Pro_2_1.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', use_container_width=True)
        pdf=pdf_bytes(summary, course_name, st.session_state.get('generated_by',''))
        st.download_button('Descargar PDF ejecutivo', pdf, file_name='AVE_Canvas_Analytics_Pro_2_1.pdf', mime='application/pdf', use_container_width=True)
