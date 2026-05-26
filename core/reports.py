from io import BytesIO
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

DEV='Ing. Christian Pocol, Ingeniero Electrónico'

def safe(v):
    if pd.isna(v): return ''
    if isinstance(v, (dict, list, tuple, set)): return str(v)
    try:
        if hasattr(v, 'tzinfo') and v.tzinfo is not None:
            return v.replace(tzinfo=None)
    except Exception:
        pass
    return v

def write_sheet(wb, title, df):
    ws = wb.create_sheet(title[:31])
    if df is None or df.empty:
        ws.append(['Sin datos']); return
    cols=list(df.columns)
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='1B2A7A')
        cell.alignment = Alignment(horizontal='center')
    for _, row in df.iterrows():
        ws.append([safe(row.get(c,'')) for c in cols])
    for col in ws.columns:
        max_len=max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len+2, 12), 45)
    ws.freeze_panes='A2'
    ws.auto_filter.ref = ws.dimensions

def excel_bytes(summary=None, submissions=None, history=None, modules=None, module_items=None, module_matrix=None, bitacora=None):
    wb=Workbook(); wb.remove(wb.active)
    for name, df in [('Resumen estudiantes', summary), ('Entregas', submissions), ('Historial', history), ('Modulos', modules), ('Items modulos', module_items), ('Matriz modulos', module_matrix), ('Bitacora', bitacora)]:
        write_sheet(wb, name, df)
    bio=BytesIO(); wb.save(bio); bio.seek(0); return bio.getvalue()

def pdf_bytes(summary, course_name='', generated_by=''):
    bio=BytesIO(); doc=SimpleDocTemplate(bio, pagesize=landscape(letter), leftMargin=25, rightMargin=25, topMargin=25, bottomMargin=25)
    styles=getSampleStyleSheet(); story=[]
    story.append(Paragraph('AVE Canvas Analytics Pro 2.1', styles['Title']))
    story.append(Paragraph(f'Curso: {course_name}', styles['Normal']))
    story.append(Paragraph(f'Generado por: {generated_by or "No indicado"}', styles['Normal']))
    story.append(Paragraph(f'Desarrollador: {DEV}', styles['Normal']))
    story.append(Spacer(1,12))
    if summary is None or summary.empty:
        story.append(Paragraph('Sin datos para reportar.', styles['Normal']))
    else:
        counts = summary['riesgo_integral'].value_counts().to_dict() if 'riesgo_integral' in summary.columns else {}
        story.append(Paragraph(f"Resumen: Bajo {counts.get('Bajo',0)} | Medio {counts.get('Medio',0)} | Alto {counts.get('Alto',0)}", styles['Heading2']))
        cols=['nombre','correo','riesgo_integral','segmento_ave','horas_sin_actividad','pendientes','atrasadas','avance_%']
        df=summary[[c for c in cols if c in summary.columns]].copy()
        risk=df[df.get('riesgo_integral','').isin(['Alto','Medio'])] if 'riesgo_integral' in df.columns else df
        data=[list(risk.columns)] + risk.fillna('').astype(str).values.tolist()
        tbl=Table(data, repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1B2A7A')),('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('GRID',(0,0),(-1,-1),0.25,colors.grey),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),
            ('VALIGN',(0,0),(-1,-1),'TOP')
        ]))
        story.append(tbl)
    doc.build(story)
    bio.seek(0); return bio.getvalue()
