import time
import requests
from urllib.parse import urljoin

class CanvasError(Exception):
    pass

class CanvasClient:
    def __init__(self, base_url: str, token: str, timeout: int = 90, retries: int = 3):
        self.base_url = base_url.rstrip('/')
        self.api = self.base_url + '/api/v1'
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {token.strip()}'})

    def _request(self, method, path, **kwargs):
        url = path if str(path).startswith('http') else self.api + '/' + str(path).lstrip('/')
        last = None
        for attempt in range(self.retries):
            try:
                r = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = r
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if not r.ok:
                    raise CanvasError(f"Canvas respondió {r.status_code}: {r.text[:800]}")
                return r
            except requests.Timeout as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
            except requests.RequestException as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        if isinstance(last, requests.Response):
            raise CanvasError(f"Canvas respondió {last.status_code}: {last.text[:800]}")
        raise CanvasError(f"No se pudo conectar con Canvas: {last}")

    def get_json(self, path, params=None):
        return self._request('GET', path, params=params).json()

    def post_json(self, path, data=None, json=None):
        return self._request('POST', path, data=data, json=json).json()

    def get_paginated(self, path, params=None):
        params = dict(params or {})
        params.setdefault('per_page', 100)
        r = self._request('GET', path, params=params)
        out = []
        while True:
            payload = r.json()
            if isinstance(payload, list):
                out.extend(payload)
            else:
                out.append(payload)
            nxt = r.links.get('next', {}).get('url')
            if not nxt:
                break
            r = self._request('GET', nxt)
        return out

    def test(self):
        return self.get_json('users/self')

    def courses(self):
        params = {'enrollment_state': 'active', 'include[]': ['term'], 'state[]': ['available']}
        return self.get_paginated('courses', params=params)

    def sections(self, course_id):
        return self.get_paginated(f'courses/{course_id}/sections', params={'include[]': ['students']})

    def enrollments(self, course_id, section_id=None, types=None):
        if types is None:
            types = ['StudentEnrollment']
        params = {'type[]': types, 'state[]': ['active', 'invited', 'creation_pending'], 'include[]': ['user']}
        if section_id:
            path = f'sections/{section_id}/enrollments'
        else:
            path = f'courses/{course_id}/enrollments'
        return self.get_paginated(path, params=params)

    def students(self, course_id, section_id=None):
        return self.enrollments(course_id, section_id, ['StudentEnrollment'])

    def staff(self, course_id):
        return self.enrollments(course_id, None, ['TeacherEnrollment', 'TaEnrollment', 'DesignerEnrollment'])

    def assignments(self, course_id):
        return self.get_paginated(f'courses/{course_id}/assignments', params={'include[]': ['submission']})

    def submissions_for_students(self, course_id, student_ids, chunk_size=25):
        all_rows = []
        ids = [str(x) for x in student_ids if str(x) not in ('None', '', 'nan')]
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i+chunk_size]
            params = {
                'student_ids[]': chunk,
                'include[]': ['submission_history', 'assignment', 'user'],
                'grouped': 'true'
            }
            data = self.get_paginated(f'courses/{course_id}/students/submissions', params=params)
            for item in data:
                # grouped endpoint may return [{'user_id':..., 'submissions':[...]}]
                if isinstance(item, dict) and isinstance(item.get('submissions'), list):
                    uid = item.get('user_id')
                    for sub in item.get('submissions', []):
                        if isinstance(sub, dict):
                            sub['_group_user_id'] = uid
                            all_rows.append(sub)
                elif isinstance(item, dict):
                    all_rows.append(item)
        return all_rows

    def modules_with_items(self, course_id):
        return self.get_paginated(f'courses/{course_id}/modules', params={'include[]': ['items']})

    def module_progress(self, course_id, module_id, student_id):
        try:
            return self.get_json(f'courses/{course_id}/modules/{module_id}', params={'include[]': ['items'], 'student_id': student_id})
        except Exception:
            return None

    def send_conversation(self, course_id, recipient_ids, subject, body, group=False, chunk_size=25):
        """Envía mensajes por Canvas Inbox. Para privacidad, group=False envía conversaciones individuales/privadas."""
        clean = []
        for r in recipient_ids:
            s = str(r).strip()
            if s and s.lower() not in ('none', 'nan') and s not in clean:
                clean.append(s)
        if not clean:
            raise CanvasError('No hay destinatarios válidos para enviar.')

        results = []
        size = len(clean) if group else chunk_size
        for i in range(0, len(clean), size):
            chunk = clean[i:i+size]
            form = []
            for rid in chunk:
                form.append(('recipients[]', rid))
            form.extend([
                ('subject', subject or 'Seguimiento académico'),
                ('body', body or ''),
                ('context_code', f'course_{course_id}'),
                ('group_conversation', 'true' if group else 'false'),
                ('mode', 'async'),
            ])
            try:
                res = self.post_json('conversations', data=form)
                results.append({'ok': True, 'destinatarios': len(chunk), 'respuesta': res})
            except CanvasError as e:
                # Fallback individual, evita que un usuario inválido bloquee todo
                if len(chunk) > 1 and not group:
                    for rid in chunk:
                        try:
                            form_one = [('recipients[]', rid), ('subject', subject or 'Seguimiento académico'), ('body', body or ''), ('context_code', f'course_{course_id}'), ('group_conversation', 'false'), ('mode', 'async')]
                            res = self.post_json('conversations', data=form_one)
                            results.append({'ok': True, 'destinatarios': 1, 'user_id': rid, 'respuesta': res})
                        except Exception as one_e:
                            results.append({'ok': False, 'destinatarios': 1, 'user_id': rid, 'error': str(one_e)})
                else:
                    results.append({'ok': False, 'destinatarios': len(chunk), 'error': str(e)})
        return results
