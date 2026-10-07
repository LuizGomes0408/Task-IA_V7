from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps
import os, io, re, uuid, time, threading, requests

# Carrega .env (útil no desenvolvimento local; no Render as variáveis vêm do painel).
# O caminho é absoluto (pasta do app.py): antes dependia da pasta de onde o app era iniciado
# e, se fosse outra, o .env não era lido e a chave da IA ficava vazia.
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
try:
    from dotenv import dotenv_values
    for _k, _v in (dotenv_values(_ENV_PATH) or {}).items():
        if _v is not None and _v.strip():          # valor vazio no .env não apaga variável do sistema
            os.environ[_k] = _v.strip().strip('"').strip("'").strip()
except Exception:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'taskai-chave-padrao-mude-em-producao')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024  # 6MB, cobre upload de avatar

# Suporte SQLite (local) e PostgreSQL (Render/produção)
db_url = os.environ.get('DATABASE_URL', 'sqlite:///taskmanager.db')
# Driver explícito: o SQLAlchemy 2.1+ passou a usar 'psycopg' (v3) por padrão em 'postgresql://',
# mas o projeto instala psycopg2 — sem isto o app não sobe no Render.
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql+psycopg2://', 1)
elif db_url.startswith('postgresql://'):
    db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
# Render/Postgres derruba conexões ociosas. Sem isso o app funciona por um tempo e depois
# começa a dar "SSL connection has been closed unexpectedly" / erro 500.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,   # testa a conexão antes de usar e reabre se tiver caído
    'pool_recycle': 280,     # recicla conexões antes do timeout do servidor
}
if db_url.startswith('postgresql'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS']['connect_args'] = {
        'keepalives': 1, 'keepalives_idle': 30, 'keepalives_interval': 10, 'keepalives_count': 5,
        'connect_timeout': 10,
    }

db = SQLAlchemy(app)

BASE_DIR    = os.path.abspath(os.path.dirname(__file__))
AVATAR_DIR  = os.path.join(BASE_DIR, 'static', 'uploads', 'avatars')
REPORT_DIR  = os.path.join(BASE_DIR, 'static', 'uploads', 'reports')
os.makedirs(AVATAR_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# ═══════════════════════════ CONFIG DE PLANOS / IA ═════════════════════════════

# Limite de mensagens diárias por tipo de conta (plano gratuito)

# IA — Groq (chave gratuita, sem cartão, em console.groq.com/keys)
def _clean_env(v):
    return (v or '').strip().strip('"').strip("'").strip()

GROQ_API_KEY  = _clean_env(os.environ.get('GROQ_API_KEY'))
GROQ_BASE_URL = (_clean_env(os.environ.get('GROQ_BASE_URL')) or 'https://api.groq.com/openai/v1').rstrip('/')
GROQ_URL      = GROQ_BASE_URL + '/chat/completions'
GROQ_MODELS_URL = GROQ_BASE_URL + '/models'
# A Groq DESATIVOU o llama-3.3-70b-versatile em 16/08/2026 (era o modelo do projeto -> a IA parou de responder).
# Substituto recomendado pela própria Groq: openai/gpt-oss-120b.
GROQ_RETIRED_MODELS = {'llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'qwen/qwen3-32b',
                       'meta-llama/llama-4-scout-17b-16e-instruct',
                       'meta-llama/llama-4-maverick-17b-128e-instruct', 'moonshotai/kimi-k2-instruct-0905',
                       'deepseek-r1-distill-llama-70b', 'gemma2-9b-it', 'llama3-70b-8192', 'llama3-8b-8192'}
GROQ_DEFAULT_MODEL = 'openai/gpt-oss-120b'
GROQ_MODEL_PREFERENCE = ['openai/gpt-oss-120b', 'qwen/qwen3.6-27b', 'openai/gpt-oss-20b']
GROQ_MODEL = _clean_env(os.environ.get('GROQ_MODEL')) or GROQ_DEFAULT_MODEL
if GROQ_MODEL in GROQ_RETIRED_MODELS:       # .env/Render antigos ainda apontam para um modelo desativado
    GROQ_MODEL = GROQ_DEFAULT_MODEL
AI_MAX_TOKENS = int(os.environ.get('AI_MAX_TOKENS', 3000))   # tamanho máximo de cada resposta
AI_REASONING  = _clean_env(os.environ.get('AI_REASONING')) or 'low'  # só para modelos gpt-oss

# ═══════════════════════════════ CONFIG DE PLANOS PAGOS ════════════════════════
# Preços exibidos na página de Planos (ambiente de demonstração — nenhuma cobrança real ocorre).
# monthly = preço por mês | annual_old = preço cheio do ano | annual = preço anual com desconto
PLAN_PRICES = {
    'especial': {
        'monthly':    float(os.environ.get('ESPECIAL_PRICE_MONTHLY', 35.80)),
        'annual_old': float(os.environ.get('ESPECIAL_ANNUAL_OLD', 390.50)),
        'annual':     float(os.environ.get('ESPECIAL_ANNUAL_PRICE', 273.00)),
    },
    'pro': {
        'monthly':    float(os.environ.get('PRO_PRICE_MONTHLY', 48.90)),
        'annual_old': float(os.environ.get('PRO_ANNUAL_OLD', 586.00)),
        'annual':     float(os.environ.get('PRO_ANNUAL_PRICE', 410.76)),
    },
}
PAID_PLANS = ('especial', 'pro')            # planos pagos existentes
PLAN_ACCOUNT = {'especial': 'comum', 'pro': 'corporativo'}   # tipo de conta de cada plano pago

ALLOWED_AVATAR_EXT = {'png', 'jpg', 'jpeg', 'webp'}

# ═══════════════════════════════ DATA/HORA PT-BR ═══════════════════════════════

MESES_PT = ['janeiro','fevereiro','março','abril','maio','junho','julho',
            'agosto','setembro','outubro','novembro','dezembro']
DIAS_PT  = ['segunda-feira','terça-feira','quarta-feira','quinta-feira',
            'sexta-feira','sábado','domingo']

def agora_br():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/Sao_Paulo'))
    except Exception:
        return datetime.utcnow()

def data_extenso(dt):
    return f"{DIAS_PT[dt.weekday()]}, {dt.day} de {MESES_PT[dt.month-1]} de {dt.year} às {dt.strftime('%H:%M')}"

def hoje_str():
    return agora_br().strftime('%Y-%m-%d')

# ═══════════════════════════════ MODELS ═══════════════════════════════════════

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    account_type  = db.Column(db.String(20), default='comum')   # comum | corporativo
    plan          = db.Column(db.String(20), default='free')    # free | especial | pro (upgrade simulado)
    plan_cycle    = db.Column(db.String(10), default='mensal')  # mensal | anual (só relevante em planos pagos)
    avatar_path   = db.Column(db.String(255), nullable=True)
    avatar_color  = db.Column(db.String(20), default='#2563eb')
    theme         = db.Column(db.String(10), default='dark')    # dark | light
    ai_msgs_used  = db.Column(db.Integer, default=0)
    ai_msgs_date  = db.Column(db.String(10), default='')
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    tasks         = db.relationship('Task', backref='owner', lazy=True, cascade='all, delete-orphan')
    employees     = db.relationship('Employee', backref='owner', lazy=True, cascade='all, delete-orphan')
    conversations = db.relationship('Conversation', backref='owner', lazy=True, cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='owner', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id, 'username': self.username, 'email': self.email,
            'account_type': self.account_type, 'plan': self.plan, 'plan_cycle': self.plan_cycle,
            'avatar_url': ('/static/uploads/avatars/' + self.avatar_path) if self.avatar_path else None,
            'avatar_color': self.avatar_color, 'theme': self.theme,
        }

    def is_paid(self):
        return self.plan in PAID_PLANS

    # Os benefícios dos planos são apenas informativos (texto na página Planos): nada é bloqueado.
    def can_report(self):
        return True

    def ai_limit(self):
        return None

    def ai_remaining(self):
        self._reset_ai_counter_if_new_day()
        return None

    def _reset_ai_counter_if_new_day(self):
        t = hoje_str()
        if self.ai_msgs_date != t:
            self.ai_msgs_date = t
            self.ai_msgs_used = 0

    def register_ai_message(self):
        self._reset_ai_counter_if_new_day()
        self.ai_msgs_used += 1


class Employee(db.Model):
    """Funcionário de uma conta corporativa (registro simples, sem login próprio)."""
    __tablename__ = 'employees'
    id         = db.Column(db.Integer, primary_key=True)
    owner_id   = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name       = db.Column(db.String(120), nullable=False)
    role       = db.Column(db.String(120), default='')
    color      = db.Column(db.String(20), default='#2563eb')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tasks      = db.relationship('Task', backref='employee', lazy=True)

    def to_dict(self):
        all_t = self.tasks
        total = len(all_t)
        done  = sum(1 for t in all_t if t.status == 'concluido')
        return {
            'id': self.id, 'name': self.name, 'role': self.role or '', 'color': self.color,
            'total': total,
            'pendente': sum(1 for t in all_t if t.status == 'pendente'),
            'em_andamento': sum(1 for t in all_t if t.status == 'em_andamento'),
            'concluido': done,
            'pct': round((done / total) * 100) if total else 0,
        }


class Task(db.Model):
    __tablename__ = 'tasks'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    priority    = db.Column(db.String(20), default='media')   # alta|media|baixa
    status      = db.Column(db.String(20), default='pendente') # pendente|em_andamento|concluido
    deadline    = db.Column(db.Date, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':           self.id,
            'name':         self.name,
            'description':  self.description or '',
            'priority':     self.priority,
            'status':       self.status,
            'deadline':     self.deadline.strftime('%Y-%m-%d') if self.deadline else None,
            'deadline_fmt': self.deadline.strftime('%d/%m/%Y') if self.deadline else None,
            'created_at':   self.created_at.isoformat(),
            'employee_id':  self.employee_id,
            'employee_name': self.employee.name if self.employee_id and self.employee else None,
        }


class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    ntype      = db.Column(db.String(30), default='info')  # task_created|task_updated|task_status|task_deleted
    title      = db.Column(db.String(160), nullable=False)
    message    = db.Column(db.String(300), default='')
    read       = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'type': self.ntype, 'title': self.title,
            'message': self.message, 'read': self.read,
            'created_at': self.created_at.isoformat(),
        }


class Conversation(db.Model):
    __tablename__ = 'conversations'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title      = db.Column(db.String(160), default='Nova conversa')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages   = db.relationship('ChatMessage', backref='conversation', lazy=True,
                                  cascade='all, delete-orphan', order_by='ChatMessage.created_at')

    def to_dict(self, with_messages=False):
        d = {'id': self.id, 'title': self.title,
             'created_at': self.created_at.isoformat(),
             'updated_at': self.updated_at.isoformat()}
        if with_messages:
            d['messages'] = [m.to_dict() for m in self.messages]
        return d


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    role            = db.Column(db.String(10), nullable=False)  # user | assistant
    content         = db.Column(db.Text, nullable=False)
    report_url      = db.Column(db.String(255), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'role': self.role, 'content': self.content,
            'report_url': self.report_url, 'created_at': self.created_at.isoformat(),
        }

# ═══════════════════════════════ AUTH ═════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session or db.session.get(User, session['user_id']) is None:
            # sem sessão, ou cookie de um usuário que não existe mais (ex.: banco recriado/expirado)
            session.clear()
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Não autorizado'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def current_user():
    return db.session.get(User, session['user_id'])

def corp_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u or u.account_type != 'corporativo':
            if request.is_json:
                return jsonify({'success': False, 'error': 'Recurso exclusivo do plano Corporativo.',
                                 'upgrade_required': True, 'redirect': '/planos'}), 403
            return redirect(url_for('planos'))
        return f(*args, **kwargs)
    return wrapper

# ═══════════════════════════════ NOTIFICAÇÕES (helper) ═════════════════════════

def notify(user_id, ntype, title, message=''):
    n = Notification(user_id=user_id, ntype=ntype, title=title, message=message)
    db.session.add(n)
    # não faz commit aqui — quem chama já está numa transação de salvar a tarefa

# ═══════════════════════════════ IA — GROQ ═════════════════════════════════════

REPORT_KEYWORDS = ['docx', 'word', 'relatório', 'relatorio', 'documento', 'exportar',
                    'baixar relatório', 'baixar relatorio', 'gerar relatório', 'gerar relatorio']

def build_ai_context(user):
    all_t = Task.query.filter_by(user_id=user.id).all()
    pend  = sum(1 for t in all_t if t.status == 'pendente')
    prog  = sum(1 for t in all_t if t.status == 'em_andamento')
    done  = sum(1 for t in all_t if t.status == 'concluido')
    ctx = (f"Data e hora atuais: {data_extenso(agora_br())} (fuso de Brasília).\n"
           f"O usuário ({user.username}) tem conta do tipo '{user.account_type}'.\n"
           f"Tarefas do usuário: {len(all_t)} no total — {pend} pendentes, {prog} em andamento, {done} concluídas.")
    if all_t:
        nomes = [t.name for t in all_t[:6]]
        ctx += f" Exemplos de tarefas: {', '.join(nomes)}."

    if user.account_type == 'corporativo':
        emps = Employee.query.filter_by(owner_id=user.id).all()
        if emps:
            ctx += "\nEquipe (funcionários cadastrados pela conta corporativa):"
            for e in emps:
                d = e.to_dict()
                ctx += (f"\n- {e.name} ({e.role or 'sem cargo'}): {d['total']} tarefa(s), "
                        f"{d['pendente']} pendente(s), {d['em_andamento']} em andamento, "
                        f"{d['concluido']} concluída(s) ({d['pct']}%).")
        else:
            ctx += "\nAinda não há funcionários cadastrados na equipe."
    return ctx


_groq_state = {'model': None}
_groq_lock = threading.Lock()
_NON_CHAT = ('whisper', 'tts', 'guard', 'orpheus', 'playai', 'safeguard', 'embed', 'distil-whisper')

def _groq_headers():
    return {'Content-Type': 'application/json', 'Authorization': f'Bearer {GROQ_API_KEY}',
            'User-Agent': 'TaskAI/1.0 (+flask; requests)', 'Accept': 'application/json'}

def _groq_error_text(resp):
    """Mensagem de erro real devolvida pela Groq (para a pessoa saber o que aconteceu)."""
    try:
        e = resp.json().get('error')
        if isinstance(e, dict):
            return (e.get('message') or e.get('code') or '')[:220]
        if e:
            return str(e)[:220]
    except Exception:
        pass
    return (resp.text or '')[:220].strip()

def _is_model_problem(resp):
    if resp.status_code not in (400, 404):
        return False
    t = (resp.text or '').lower()
    return 'model' in t and any(k in t for k in ('decommission', 'not found', 'does not exist', 'no longer',
                                                  'not supported', 'deprecat', 'model_not_found', 'invalid'))

def _discover_model():
    """Pergunta à Groq quais modelos existem hoje e escolhe o melhor disponível."""
    try:
        r = requests.get(GROQ_MODELS_URL, headers=_groq_headers(), timeout=15)
        if r.status_code != 200:
            return None
        ids = [m.get('id', '') for m in (r.json().get('data') or []) if m.get('id')]
        ids = [i for i in ids if not any(x in i.lower() for x in _NON_CHAT) and i not in GROQ_RETIRED_MODELS]
        for pref in GROQ_MODEL_PREFERENCE:
            if pref in ids:
                return pref
        return ids[0] if ids else None
    except Exception:
        return None

def _groq_body(model, messages, max_tokens):
    body = {'model': model, 'messages': messages, 'temperature': 0.7, 'max_completion_tokens': max_tokens}
    if model.startswith('openai/gpt-oss') and AI_REASONING in ('low', 'medium', 'high'):
        body['reasoning_effort'] = AI_REASONING
    return body

def call_groq(system_prompt, history_msgs, user_message):
    if not GROQ_API_KEY or GROQ_API_KEY.startswith('coloque_aqui'):
        return None, ('⚠️ Chave da IA (Groq) não configurada. Peça uma chave gratuita em '
                       'console.groq.com/keys e coloque em GROQ_API_KEY no arquivo .env '
                       '(ou nas variáveis de ambiente do Render).')
    messages = [{'role': 'system', 'content': system_prompt}]
    for h in history_msgs[-30:]:
        role = 'assistant' if h.get('role') == 'assistant' else 'user'
        if h.get('content'):
            messages.append({'role': role, 'content': h['content']})
    messages.append({'role': 'user', 'content': user_message})

    model = _groq_state['model'] or GROQ_MODEL
    max_tokens = AI_MAX_TOKENS
    tried_discovery = False
    try:
        for _ in range(4):
            resp = requests.post(GROQ_URL, headers=_groq_headers(),
                                 json=_groq_body(model, messages, max_tokens), timeout=(10, 100))
            if resp.status_code == 200:
                break
            if _is_model_problem(resp) and not tried_discovery:       # modelo desativado/inexistente
                tried_discovery = True
                with _groq_lock:
                    novo = _discover_model()
                if novo and novo != model:
                    model = novo
                    _groq_state['model'] = novo
                    continue
            if resp.status_code == 413 and max_tokens > 800:          # pedido grande demais p/ o limite da conta
                max_tokens //= 2
                if len(messages) > 6:
                    messages = [messages[0]] + messages[-5:]
                continue
            break
        else:
            return None, '⚠️ Não foi possível obter resposta da IA agora. Tente novamente.'

        if resp.status_code == 401:
            return None, '⚠️ A Groq recusou a chave (401). Confira se GROQ_API_KEY está correta e sem espaços.'
        if resp.status_code == 403:
            return None, f'⚠️ Acesso negado pela Groq (403): {_groq_error_text(resp)}'
        if resp.status_code == 429:
            return None, ('⚠️ O limite de uso da sua conta Groq foi atingido por enquanto. '
                           'Aguarde alguns instantes e tente de novo.')
        if resp.status_code != 200:
            return None, f'⚠️ A Groq retornou erro {resp.status_code}: {_groq_error_text(resp)}'

        if model != GROQ_MODEL and not _groq_state['model']:
            _groq_state['model'] = model
        data = resp.json()
        choices = data.get('choices') or []
        if not choices:
            return None, '⚠️ A IA não retornou uma resposta. Tente novamente.'
        msg = choices[0].get('message', {}) or {}
        text = (msg.get('content') or '').strip()
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()
        if not text:
            if choices[0].get('finish_reason') == 'length':
                return None, '⚠️ A resposta ficou grande demais. Peça de novo de forma mais específica.'
            return None, '⚠️ A IA não retornou texto. Tente novamente.'
        return text, None
    except requests.exceptions.Timeout:
        return None, '⚠️ A IA demorou demais para responder. Tente novamente.'
    except requests.exceptions.SSLError:
        return None, '⚠️ Falha de segurança (SSL) ao conectar com a Groq. Verifique data/hora do computador e antivírus/proxy.'
    except requests.exceptions.ConnectionError:
        return None, '⚠️ Não foi possível conectar à API da Groq. Verifique a internet, firewall ou proxy.'
    except Exception as e:
        return None, f'⚠️ Erro ao contatar a IA: {str(e)[:160]}'

# ═══════════════════════════════ RELATÓRIO DOCX ════════════════════════════════

_REPORT_LOCK = threading.Lock()

def _limpar_relatorios_antigos(max_idade=1800):
    """Apaga .docx antigos: o disco do Render é efêmero e pequeno."""
    try:
        agora = time.time()
        for n in os.listdir(REPORT_DIR):
            if n.endswith('.docx'):
                fp = os.path.join(REPORT_DIR, n)
                if agora - os.path.getmtime(fp) > max_idade:
                    os.remove(fp)
    except OSError:
        pass

def gerar_relatorio_docx(user, scope='me'):
    with _REPORT_LOCK:
        _limpar_relatorios_antigos()
        return _gerar_relatorio_docx(user, scope)

def _gerar_relatorio_docx(user, scope='me'):
    """Gera um único .docx com texto analítico, uma 'mini planilha' (tabelas estilizadas
    como planilha, com cabeçalho colorido) e gráficos (barras/pizza) embutidos como imagens."""
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import matplotlib
    matplotlib.use('Agg')  # backend sem interface gráfica — necessário em servidor (Render)
    import matplotlib.pyplot as plt

    def shade(cell, color_hex):
        """Pinta o fundo de uma célula — é o que dá a 'cara de planilha' às tabelas."""
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), color_hex)
        tcPr.append(shd)

    def set_cell(cell, text, bold=False, color=None, size=9.5, center=False):
        cell.text = ''
        p = cell.paragraphs[0]
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(str(text))
        r.font.bold = bold
        r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color

    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(10.5)

    doc.add_heading('Relatório de Tarefas — TaskAI', level=0)
    sub = doc.add_paragraph(f'Gerado em {data_extenso(agora_br())} · Conta: {user.username} '
                             f'({"Corporativo" if user.account_type == "corporativo" else "Comum"})')
    sub.runs[0].font.size = Pt(10)
    sub.runs[0].font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    all_tasks = Task.query.filter_by(user_id=user.id).all()
    hoje = agora_br().date()

    def stats_de(tasks):
        total = len(tasks)
        pend  = sum(1 for t in tasks if t.status == 'pendente')
        prog  = sum(1 for t in tasks if t.status == 'em_andamento')
        done  = sum(1 for t in tasks if t.status == 'concluido')
        atrasadas = sum(1 for t in tasks if t.deadline and t.deadline < hoje and t.status != 'concluido')
        pct = round((done / total) * 100) if total else 0
        return {'total': total, 'pendente': pend, 'em_andamento': prog, 'concluido': done,
                'atrasadas': atrasadas, 'pct': pct}

    # ── Gráficos (matplotlib → PNG em memória → embutido no docx) ──
    def grafico_status(s, titulo):
        labels  = ['Pendentes', 'Em andamento', 'Concluídas']
        valores = [s['pendente'], s['em_andamento'], s['concluido']]
        cores   = ['#f59e0b', '#2563eb', '#10b981']
        fig, ax = plt.subplots(figsize=(5.7, 2.9))
        bars = ax.bar(labels, valores, color=cores, width=0.55)
        ax.set_title(titulo, fontsize=11, fontweight='bold', color='#1f2937')
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
        ax.set_ylabel('Nº de tarefas', fontsize=9)
        ax.tick_params(labelsize=9)
        maxv = max(valores) if valores and max(valores) > 0 else 1
        ax.set_ylim(0, maxv * 1.25)
        for b in bars:
            hgt = b.get_height()
            ax.annotate(str(int(hgt)), (b.get_x() + b.get_width() / 2, hgt),
                        ha='center', va='bottom', fontsize=9, fontweight='bold')
        fig.tight_layout()
        buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=160); plt.close(fig); buf.seek(0)
        return buf

    def grafico_pizza(s, titulo):
        labels, valores, cores = [], [], []
        for lbl, val, cor in [('Pendentes', s['pendente'], '#f59e0b'),
                               ('Em andamento', s['em_andamento'], '#2563eb'),
                               ('Concluídas', s['concluido'], '#10b981')]:
            if val > 0:
                labels.append(lbl); valores.append(val); cores.append(cor)
        if not valores:
            valores, labels, cores = [1], ['Sem tarefas'], ['#9ca3af']
        fig, ax = plt.subplots(figsize=(4.3, 3.4))
        ax.pie(valores, labels=labels, colors=cores,
               autopct=lambda p: f'{p:.0f}%' if p > 0 else '', startangle=90,
               textprops={'fontsize': 9})
        ax.set_title(titulo, fontsize=11, fontweight='bold', color='#1f2937')
        fig.tight_layout()
        buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=160); plt.close(fig); buf.seek(0)
        return buf

    def grafico_equipe(emps):
        dados = sorted([(e.name, e.to_dict()['pct']) for e in emps], key=lambda x: x[1])
        nomes = [d[0] for d in dados]; pcts = [d[1] for d in dados]
        fig, ax = plt.subplots(figsize=(5.7, max(2.3, 0.48 * len(dados) + 1)))
        bars = ax.barh(nomes, pcts, color='#2563eb', height=0.55)
        ax.set_xlim(0, 100)
        ax.set_xlabel('% de tarefas concluídas', fontsize=9)
        ax.set_title('Progresso de conclusão por funcionário', fontsize=11, fontweight='bold', color='#1f2937')
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=9)
        for b in bars:
            w = b.get_width()
            ax.annotate(f'{int(w)}%', (w, b.get_y() + b.get_height() / 2), va='center', ha='left',
                        fontsize=8, xytext=(4, 0), textcoords='offset points')
        fig.tight_layout()
        buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=160); plt.close(fig); buf.seek(0)
        return buf

    # ── "Mini planilha" — tabela com cabeçalho colorido e linhas sombreadas ──
    def planilha_resumo(s, titulo):
        doc.add_heading(titulo, level=1)
        table = doc.add_table(rows=2, cols=5)
        table.style = 'Table Grid'
        headers = ['Total', 'Pendentes', 'Em andamento', 'Concluídas', '% concluído']
        for i, txt in enumerate(headers):
            c = table.rows[0].cells[i]
            set_cell(c, txt, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF), center=True)
            shade(c, '1D4ED8')
        vals = [s['total'], s['pendente'], s['em_andamento'], s['concluido'], f"{s['pct']}%"]
        for i, v in enumerate(vals):
            c = table.rows[1].cells[i]
            set_cell(c, v, center=True)
            shade(c, 'EFF6FF')
        if s['atrasadas']:
            p = doc.add_paragraph()
            r = p.add_run(f"⚠ {s['atrasadas']} tarefa(s) com prazo vencido e ainda não concluída(s).")
            r.font.color.rgb = RGBColor(0xB4, 0x53, 0x09); r.font.bold = True; r.font.size = Pt(10)

    def tabela_tarefas(tasks, titulo, mostrar_func=False):
        doc.add_heading(titulo, level=2)
        if not tasks:
            doc.add_paragraph('Nenhuma tarefa cadastrada.')
            return
        cols = 5 + (1 if mostrar_func else 0)
        table = doc.add_table(rows=1, cols=cols)
        table.style = 'Table Grid'
        headers = ['Tarefa', 'Prioridade', 'Status', 'Prazo']
        if mostrar_func:
            headers.append('Funcionário')
        headers.append('Descrição')
        for i, txt in enumerate(headers):
            c = table.rows[0].cells[i]
            set_cell(c, txt, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
            shade(c, '1D4ED8')
        pmap = {'alta': 'Alta', 'media': 'Média', 'baixa': 'Baixa'}
        smap = {'pendente': 'Pendente', 'em_andamento': 'Em andamento', 'concluido': 'Concluído'}
        for idx, t in enumerate(tasks):
            row = table.add_row().cells
            vencida = bool(t.deadline and t.deadline < hoje and t.status != 'concluido')
            valores = [t.name, pmap.get(t.priority, t.priority), smap.get(t.status, t.status),
                       (t.deadline.strftime('%d/%m/%Y') + (' ⚠' if vencida else '')) if t.deadline else '—']
            if mostrar_func:
                valores.append(t.employee.name if t.employee_id and t.employee else '—')
            valores.append((t.description or '—')[:200])
            bg = 'F8FAFC' if idx % 2 == 0 else 'FFFFFF'
            for i, v in enumerate(valores):
                c = row[i]
                set_cell(c, v, size=9)
                shade(c, bg)

    # ── Texto — resumo executivo escrito dinamicamente a partir dos dados ──
    s_geral = stats_de(all_tasks)
    doc.add_heading('Resumo executivo', level=1)
    if scope == 'team' and user.account_type == 'corporativo':
        emps = Employee.query.filter_by(owner_id=user.id).all()
        texto = (f"A equipe possui {len(emps)} funcionário(s) cadastrado(s) e {s_geral['total']} tarefa(s) "
                 f"no total. Até o momento, {s_geral['concluido']} tarefa(s) foram concluídas "
                 f"({s_geral['pct']}% do total), {s_geral['em_andamento']} estão em andamento e "
                 f"{s_geral['pendente']} ainda não foram iniciadas.")
        if s_geral['atrasadas']:
            texto += f" Atenção: {s_geral['atrasadas']} tarefa(s) estão com o prazo vencido."
        if emps:
            com_tarefas = [e for e in emps if e.to_dict()['total'] > 0]
            if com_tarefas:
                lider = max(com_tarefas, key=lambda e: e.to_dict()['pct'])
                texto += (f" {lider.name} lidera o progresso da equipe, com {lider.to_dict()['pct']}% "
                          f"das tarefas concluídas.")
            sem_tarefa = [e.name for e in emps if e.to_dict()['total'] == 0]
            if sem_tarefa:
                verbo = 'têm' if len(sem_tarefa) > 1 else 'tem'
                texto += f" {', '.join(sem_tarefa)} ainda não {verbo} tarefas atribuídas."
        doc.add_paragraph(texto)
    else:
        texto = (f"Você tem {s_geral['total']} tarefa(s) cadastrada(s). Já concluiu {s_geral['concluido']} "
                 f"({s_geral['pct']}%), tem {s_geral['em_andamento']} em andamento e "
                 f"{s_geral['pendente']} pendente(s).")
        if s_geral['atrasadas']:
            texto += f" Existem {s_geral['atrasadas']} tarefa(s) com prazo vencido — vale priorizá-las."
        elif s_geral['total'] and s_geral['pct'] == 100:
            texto += " Parabéns, todas as suas tarefas estão em dia!"
        doc.add_paragraph(texto)

    # ── Gráficos ──
    doc.add_heading('Gráficos', level=1)
    doc.add_picture(grafico_status(s_geral, 'Distribuição geral de tarefas por status'), width=Inches(5.7))
    doc.add_picture(grafico_pizza(s_geral, 'Proporção de conclusão'), width=Inches(3.6))

    if scope == 'team' and user.account_type == 'corporativo':
        emps = Employee.query.filter_by(owner_id=user.id).all()
        if emps:
            doc.add_picture(grafico_equipe(emps), width=Inches(5.7))

        planilha_resumo(s_geral, 'Mini planilha — Resumo geral da equipe')

        if emps:
            doc.add_heading('Mini planilha — Progresso por funcionário', level=1)
            table = doc.add_table(rows=1, cols=5)
            table.style = 'Table Grid'
            for i, txt in enumerate(['Funcionário', 'Total', 'Pendentes', 'Em andamento', 'Concluídas (%)']):
                c = table.rows[0].cells[i]
                set_cell(c, txt, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
                shade(c, '1D4ED8')
            for idx, e in enumerate(emps):
                d = e.to_dict()
                row = table.add_row().cells
                valores = [e.name + (f' — {e.role}' if e.role else ''), d['total'], d['pendente'],
                           d['em_andamento'], f"{d['concluido']} ({d['pct']}%)"]
                bg = 'F8FAFC' if idx % 2 == 0 else 'FFFFFF'
                for i, v in enumerate(valores):
                    c = row[i]
                    set_cell(c, v, size=9)
                    shade(c, bg)

        doc.add_heading('Detalhamento de tarefas', level=1)
        tabela_tarefas(all_tasks, 'Todas as tarefas da equipe (feitas, em andamento e não feitas)', mostrar_func=True)
    else:
        planilha_resumo(s_geral, 'Mini planilha — Resumo das suas tarefas')
        tabela_tarefas(all_tasks, 'Detalhamento das tarefas', mostrar_func=False)

    footer = doc.add_paragraph('Gerado automaticamente pelo assistente de IA do TaskAI.')
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.runs[0].font.size = Pt(8)
    footer.runs[0].font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    fname = f'relatorio_{scope}_{user.id}_{uuid.uuid4().hex[:8]}.docx'
    fpath = os.path.join(REPORT_DIR, fname)
    doc.save(fpath)
    return fname


def deve_gerar_relatorio(msg):
    m = msg.lower()
    return any(k in m for k in REPORT_KEYWORDS)

# ═══════════════════════════════ ERROS / ROBUSTEZ ══════════════════════════════

@app.teardown_request
def _cleanup_session(exc):
    if exc is not None:
        db.session.rollback()
    db.session.remove()

@app.errorhandler(413)
def _too_large(e):
    return jsonify({'success': False, 'error': 'Arquivo muito grande (máx. 6 MB).'}), 413

@app.errorhandler(404)
def _not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Não encontrado.'}), 404
    if request.path.startswith('/static/'):
        return ('Não encontrado', 404)
    return redirect(url_for('login'))

@app.errorhandler(500)
def _server_error(e):
    db.session.rollback()
    app.logger.exception('Erro 500 em %s', request.path)
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({'success': False, 'error': 'Erro interno. Tente novamente em instantes.'}), 500
    return ('<!DOCTYPE html><meta charset="utf-8"><title>Erro — TaskAI</title>'
            '<body style="font-family:system-ui;background:#0b1220;color:#e6edf7;display:grid;place-items:center;height:100vh;margin:0">'
            '<div style="text-align:center"><h2>Algo deu errado</h2>'
            '<p>Tivemos um problema temporário. <a style="color:#60a5fa" href="/">Voltar ao início</a></p></div>'), 500

# ═══════════════════════════════ PAGES ════════════════════════════════════════

@app.route('/healthz')
def healthz():
    """Health check do Render — confirma que o app e o banco estão respondendo."""
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'detail': str(e)[:200]}), 500

@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user      = current_user()
    all_tasks = Task.query.filter_by(user_id=user.id).all()
    recent    = Task.query.filter_by(user_id=user.id)\
                          .order_by(Task.created_at.desc()).limit(6).all()
    stats = {
        'total':        len(all_tasks),
        'pendente':     sum(1 for t in all_tasks if t.status == 'pendente'),
        'em_andamento': sum(1 for t in all_tasks if t.status == 'em_andamento'),
        'concluido':    sum(1 for t in all_tasks if t.status == 'concluido'),
    }
    employees = Employee.query.filter_by(owner_id=user.id).all() if user.account_type == 'corporativo' else []
    return render_template('dashboard.html', user=user, stats=stats, recent_tasks=recent, employees=employees)

@app.route('/tasks')
@login_required
def tasks():
    user      = current_user()
    search    = request.args.get('search', '')
    employees = Employee.query.filter_by(owner_id=user.id).all() if user.account_type == 'corporativo' else []
    return render_template('tasks.html', user=user, initial_search=search, employees=employees)

@app.route('/settings')
@login_required
def settings():
    user = current_user()
    return render_template('settings.html', user=user)

@app.route('/chat')
@login_required
def chat_page():
    user = current_user()
    return render_template('chat.html', user=user)

@app.route('/equipe')
@login_required
@corp_required
def equipe():
    user = current_user()
    employees = Employee.query.filter_by(owner_id=user.id).order_by(Employee.created_at.desc()).all()
    return render_template('equipe.html', user=user, employees=[e.to_dict() for e in employees])

@app.route('/planos')
@login_required
def planos():
    user = current_user()
    plans = {}
    for key, pr in PLAN_PRICES.items():
        plans[key] = dict(pr, saving=round(pr['annual_old'] - pr['annual'], 2),
                          pct=round((1 - pr['annual'] / pr['annual_old']) * 100),
                          per_month=round(pr['annual'] / 12, 2))
    return render_template('planos.html', user=user, plans=plans)

# ═══════════════════════════════ AUTH API ═════════════════════════════════════

@app.route('/api/login', methods=['POST'])
def api_login():
    d    = request.get_json()
    user = User.query.filter_by(email=d.get('email', '').strip().lower()).first()
    if user and check_password_hash(user.password_hash, d.get('password', '')):
        session.permanent = True
        session['user_id']  = user.id
        session['username'] = user.username
        return jsonify({'success': True, 'redirect': '/dashboard'})
    return jsonify({'success': False, 'error': 'Email ou senha incorretos'}), 401

@app.route('/api/register', methods=['POST'])
def api_register():
    d        = request.get_json()
    username = d.get('username', '').strip()
    email    = d.get('email', '').strip().lower()
    password = d.get('password', '')
    acc_type = d.get('account_type', 'comum')
    if acc_type not in ('comum', 'corporativo'):
        acc_type = 'comum'

    if not username or not email or not password:
        return jsonify({'success': False, 'error': 'Todos os campos são obrigatórios'}), 400
    if len(username) < 2:
        return jsonify({'success': False, 'error': 'Nome deve ter pelo menos 2 caracteres'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'error': 'Senha deve ter pelo menos 6 caracteres'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'error': 'Este email já está em uso'}), 400

    palette = ['#2563eb', '#7c3aed', '#0d9488', '#db2777', '#ea580c', '#16a34a']
    user = User(username=username, email=email,
                password_hash=generate_password_hash(password),
                account_type=acc_type,
                avatar_color=palette[hash(email) % len(palette)])
    db.session.add(user)
    db.session.commit()

    session.permanent  = True
    session['user_id'] = user.id
    session['username']= user.username
    return jsonify({'success': True, 'redirect': '/dashboard'})

# ═══════════════════════════════ TASKS API ════════════════════════════════════

@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    status = request.args.get('status', 'all')
    sort   = request.args.get('sort', 'newest')
    search = request.args.get('search', '').strip()

    q = Task.query.filter_by(user_id=session['user_id'])
    if status != 'all':
        q = q.filter_by(status=status)
    if search:
        q = q.filter(Task.name.ilike(f'%{search}%'))
    if sort == 'newest':
        q = q.order_by(Task.created_at.desc())
    elif sort == 'oldest':
        q = q.order_by(Task.created_at.asc())

    tasks_list = q.all()
    pmap = {'alta': 1, 'media': 2, 'baixa': 3}
    if sort == 'priority_high':
        tasks_list.sort(key=lambda t: pmap.get(t.priority, 4))
    elif sort == 'priority_low':
        tasks_list.sort(key=lambda t: pmap.get(t.priority, 4), reverse=True)

    all_t = Task.query.filter_by(user_id=session['user_id']).all()
    stats = {
        'total':        len(all_t),
        'pendente':     sum(1 for t in all_t if t.status == 'pendente'),
        'em_andamento': sum(1 for t in all_t if t.status == 'em_andamento'),
        'concluido':    sum(1 for t in all_t if t.status == 'concluido'),
    }
    return jsonify({'tasks': [t.to_dict() for t in tasks_list], 'stats': stats})


@app.route('/api/tasks/search')
@login_required
def search_tasks():
    q = request.args.get('q', '').strip()
    if len(q) < 1:
        return jsonify({'tasks': []})
    tasks = Task.query.filter(
        Task.user_id == session['user_id'],
        Task.name.ilike(f'%{q}%')
    ).limit(8).all()
    return jsonify({'tasks': [t.to_dict() for t in tasks]})


@app.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    d    = request.get_json()
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Nome da tarefa é obrigatório'}), 400

    deadline = None
    if d.get('deadline'):
        try:
            deadline = datetime.strptime(d['deadline'], '%Y-%m-%d').date()
        except Exception:
            pass

    user = current_user()
    employee_id = None
    if user.account_type == 'corporativo' and d.get('employee_id'):
        try:
            eid = int(d['employee_id'])
            if Employee.query.filter_by(id=eid, owner_id=user.id).first():
                employee_id = eid
        except (ValueError, TypeError):
            pass

    task = Task(
        user_id     = user.id,
        employee_id = employee_id,
        name        = name,
        description = d.get('description', '').strip(),
        priority    = d.get('priority', 'media'),
        status      = 'pendente',
        deadline    = deadline,
    )
    db.session.add(task)
    notify(user.id, 'task_created', 'Nova tarefa criada', f'"{name}" foi adicionada.')
    db.session.commit()
    return jsonify({'success': True, 'task': task.to_dict()})


@app.route('/api/tasks/<int:tid>', methods=['PUT'])
@login_required
def update_task(tid):
    task = Task.query.filter_by(id=tid, user_id=session['user_id']).first()
    if not task:
        return jsonify({'success': False, 'error': 'Tarefa não encontrada'}), 404
    d = request.get_json()
    user = current_user()

    status_changed = False
    if 'name'        in d and d['name'].strip(): task.name        = d['name'].strip()
    if 'description' in d:                       task.description = d['description'].strip()
    if 'priority'    in d:                       task.priority    = d['priority']
    if 'status'      in d and d['status'] != task.status:
        task.status = d['status']
        status_changed = True
    if 'deadline'    in d:
        task.deadline = None
        if d['deadline']:
            try: task.deadline = datetime.strptime(d['deadline'], '%Y-%m-%d').date()
            except Exception: pass
    if 'employee_id' in d and user.account_type == 'corporativo':
        if d['employee_id'] in (None, '', 'null'):
            task.employee_id = None
        else:
            try:
                eid = int(d['employee_id'])
                if Employee.query.filter_by(id=eid, owner_id=user.id).first():
                    task.employee_id = eid
            except (ValueError, TypeError):
                pass

    task.updated_at = datetime.utcnow()
    if status_changed:
        smap = {'pendente': 'Pendente', 'em_andamento': 'Em andamento', 'concluido': 'Concluído'}
        notify(user.id, 'task_status', 'Status de tarefa alterado',
               f'"{task.name}" agora está: {smap.get(task.status, task.status)}.')
    else:
        notify(user.id, 'task_updated', 'Tarefa atualizada', f'"{task.name}" foi editada.')
    db.session.commit()
    return jsonify({'success': True, 'task': task.to_dict()})


@app.route('/api/tasks/<int:tid>', methods=['DELETE'])
@login_required
def delete_task(tid):
    task = Task.query.filter_by(id=tid, user_id=session['user_id']).first()
    if not task:
        return jsonify({'success': False, 'error': 'Tarefa não encontrada'}), 404
    nome = task.name
    db.session.delete(task)
    notify(session['user_id'], 'task_deleted', 'Tarefa removida', f'"{nome}" foi excluída.')
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/tasks/bulk-delete', methods=['POST'])
@login_required
def bulk_delete():
    ids = request.get_json().get('ids', [])
    if ids:
        Task.query.filter(
            Task.id.in_(ids),
            Task.user_id == session['user_id']
        ).delete(synchronize_session=False)
        notify(session['user_id'], 'task_deleted', 'Tarefas removidas',
               f'{len(ids)} tarefa(s) excluída(s) em lote.')
        db.session.commit()
    return jsonify({'success': True})

# ═══════════════════════════════ FUNCIONÁRIOS (equipe) ═════════════════════════

@app.route('/api/employees', methods=['GET'])
@login_required
@corp_required
def list_employees():
    emps = Employee.query.filter_by(owner_id=session['user_id']).order_by(Employee.created_at.desc()).all()
    return jsonify({'employees': [e.to_dict() for e in emps]})


@app.route('/api/employees', methods=['POST'])
@login_required
@corp_required
def create_employee():
    user = current_user()
    d = request.get_json()
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Nome do funcionário é obrigatório'}), 400
    palette = ['#2563eb', '#7c3aed', '#0d9488', '#db2777', '#ea580c', '#16a34a', '#0891b2']
    emp = Employee(owner_id=user.id, name=name, role=d.get('role', '').strip(),
                    color=palette[hash(name + str(uuid.uuid4())) % len(palette)])
    db.session.add(emp)
    db.session.commit()
    return jsonify({'success': True, 'employee': emp.to_dict()})


@app.route('/api/employees/<int:eid>', methods=['DELETE'])
@login_required
@corp_required
def delete_employee(eid):
    emp = Employee.query.filter_by(id=eid, owner_id=session['user_id']).first()
    if not emp:
        return jsonify({'success': False, 'error': 'Funcionário não encontrado'}), 404
    db.session.delete(emp)
    db.session.commit()
    return jsonify({'success': True})

# ═══════════════════════════════ RELATÓRIO API ═════════════════════════════════

@app.route('/api/report/docx')
@login_required
def download_report():
    user  = current_user()
    scope = request.args.get('scope', 'me')
    if scope == 'team' and user.account_type != 'corporativo':
        scope = 'me'
    fname = gerar_relatorio_docx(user, scope=scope)
    fpath = os.path.join(REPORT_DIR, fname)
    nice_name = 'relatorio_equipe.docx' if scope == 'team' else 'relatorio_tarefas.docx'
    with open(fpath, 'rb') as fh:
        data = io.BytesIO(fh.read())
    try:
        os.remove(fpath)
    except OSError:
        pass
    return send_file(data, as_attachment=True, download_name=nice_name,
                      mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

# ═══════════════════════════════ NOTIFICAÇÕES API ══════════════════════════════

@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=session['user_id'])\
                                .order_by(Notification.created_at.desc()).limit(30).all()
    unread = Notification.query.filter_by(user_id=session['user_id'], read=False).count()
    return jsonify({'notifications': [n.to_dict() for n in notifs], 'unread': unread})


@app.route('/api/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    d = request.get_json() or {}
    nid = d.get('id')
    q = Notification.query.filter_by(user_id=session['user_id'])
    if nid:
        q = q.filter_by(id=nid)
    q.update({'read': True})
    db.session.commit()
    return jsonify({'success': True})

# ═══════════════════════════════ USER API ═════════════════════════════════════

@app.route('/api/user/update', methods=['PUT'])
@login_required
def update_user():
    d    = request.get_json()
    user = current_user()

    new_username = d.get('username', '').strip()
    new_email    = d.get('email', '').strip().lower()

    if new_username:
        user.username       = new_username
        session['username'] = new_username
    if new_email and new_email != user.email:
        if User.query.filter_by(email=new_email).first():
            return jsonify({'success': False, 'error': 'Email já em uso'}), 400
        user.email = new_email

    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


@app.route('/api/user/password', methods=['PUT'])
@login_required
def change_password():
    d    = request.get_json()
    user = current_user()
    if not check_password_hash(user.password_hash, d.get('current_password', '')):
        return jsonify({'success': False, 'error': 'Senha atual incorreta'}), 400
    new_pw = d.get('new_password', '')
    if len(new_pw) < 6:
        return jsonify({'success': False,
                        'error': 'Nova senha deve ter pelo menos 6 caracteres'}), 400
    user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/user/delete', methods=['DELETE'])
@login_required
def delete_user():
    d    = request.get_json()
    user = current_user()
    if not check_password_hash(user.password_hash, d.get('password', '')):
        return jsonify({'success': False, 'error': 'Senha incorreta'}), 400
    if user.avatar_path:
        try: os.remove(os.path.join(AVATAR_DIR, user.avatar_path))
        except OSError: pass
    db.session.delete(user)
    db.session.commit()
    session.clear()
    return jsonify({'success': True})


@app.route('/api/user/theme', methods=['PUT'])
@login_required
def set_theme():
    d = request.get_json() or {}
    t = d.get('theme', 'dark')
    if t not in ('dark', 'light'):
        t = 'dark'
    user = current_user()
    user.theme = t
    db.session.commit()
    return jsonify({'success': True, 'theme': t})


@app.route('/api/user/avatar-color', methods=['PUT'])
@login_required
def set_avatar_color():
    d = request.get_json() or {}
    color = d.get('color', '').strip()
    import re
    if not re.match(r'^#[0-9a-fA-F]{6}$', color):
        return jsonify({'success': False, 'error': 'Cor inválida'}), 400
    user = current_user()
    user.avatar_color = color
    db.session.commit()
    return jsonify({'success': True, 'avatar_color': color})


@app.route('/api/user/avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'Nenhum arquivo enviado'}), 400
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nenhum arquivo selecionado'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_AVATAR_EXT:
        return jsonify({'success': False, 'error': 'Formato inválido. Use PNG, JPG ou WEBP.'}), 400

    try:
        from PIL import Image, ImageOps
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGB')
        w, h = img.size
        s = min(w, h)
        img = img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        img = img.resize((256, 256))
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível processar a imagem.'}), 400

    user = current_user()
    if user.avatar_path:
        try: os.remove(os.path.join(AVATAR_DIR, user.avatar_path))
        except OSError: pass

    fname = f'user_{user.id}_{uuid.uuid4().hex[:10]}.jpg'
    img.save(os.path.join(AVATAR_DIR, fname), 'JPEG', quality=88)
    user.avatar_path = fname
    db.session.commit()
    return jsonify({'success': True, 'avatar_url': '/static/uploads/avatars/' + fname})


@app.route('/api/user/avatar', methods=['DELETE'])
@login_required
def remove_avatar():
    user = current_user()
    if user.avatar_path:
        try: os.remove(os.path.join(AVATAR_DIR, user.avatar_path))
        except OSError: pass
        user.avatar_path = None
        db.session.commit()
    return jsonify({'success': True})

# ═══════════════════════════════ PLANOS API ════════════════════════════════════

@app.route('/api/plans/upgrade', methods=['POST'])
@login_required
def upgrade_plan():
    """Ativação de demonstração — não processa pagamento real."""
    d = request.get_json(silent=True) or {}
    cycle = d.get('cycle', 'mensal')
    if cycle not in ('mensal', 'anual'):
        cycle = 'mensal'
    plan = d.get('plan', 'pro')
    if plan not in PAID_PLANS:
        return jsonify({'success': False, 'error': 'Plano inválido.'}), 400
    user = current_user()
    if user.account_type != PLAN_ACCOUNT[plan]:
        nome = 'pessoais' if PLAN_ACCOUNT[plan] == 'comum' else 'empresariais'
        return jsonify({'success': False, 'error': f'Este plano é para contas {nome}.'}), 400
    user.plan = plan
    user.plan_cycle = cycle
    db.session.commit()
    return jsonify({'success': True, 'plan': plan, 'plan_cycle': cycle})


@app.route('/api/plans/downgrade', methods=['POST'])
@login_required
def downgrade_plan():
    user = current_user()
    user.plan = 'free'
    user.plan_cycle = 'mensal'
    db.session.commit()
    return jsonify({'success': True, 'plan': 'free'})

# ═══════════════════════════════ CHAT / CONVERSAS API ══════════════════════════

def get_or_create_active_conversation(user_id):
    conv = Conversation.query.filter_by(user_id=user_id).order_by(Conversation.updated_at.desc()).first()
    if not conv:
        conv = Conversation(user_id=user_id, title='Nova conversa')
        db.session.add(conv)
        db.session.commit()
    return conv


@app.route('/api/chat/active', methods=['GET'])
@login_required
def chat_active():
    conv = get_or_create_active_conversation(session['user_id'])
    return jsonify({'conversation': conv.to_dict(with_messages=True)})


@app.route('/api/chat/conversations', methods=['GET'])
@login_required
def list_conversations():
    convs = Conversation.query.filter_by(user_id=session['user_id'])\
                               .order_by(Conversation.updated_at.desc()).all()
    return jsonify({'conversations': [c.to_dict() for c in convs]})


@app.route('/api/chat/conversations', methods=['POST'])
@login_required
def new_conversation():
    conv = Conversation(user_id=session['user_id'], title='Nova conversa')
    db.session.add(conv)
    db.session.commit()
    return jsonify({'success': True, 'conversation': conv.to_dict(with_messages=True)})


@app.route('/api/chat/conversations/<int:cid>', methods=['GET'])
@login_required
def get_conversation(cid):
    conv = Conversation.query.filter_by(id=cid, user_id=session['user_id']).first()
    if not conv:
        return jsonify({'error': 'Conversa não encontrada'}), 404
    return jsonify({'conversation': conv.to_dict(with_messages=True)})


@app.route('/api/chat/conversations/<int:cid>', methods=['DELETE'])
@login_required
def delete_conversation(cid):
    conv = Conversation.query.filter_by(id=cid, user_id=session['user_id']).first()
    if not conv:
        return jsonify({'success': False, 'error': 'Conversa não encontrada'}), 404
    db.session.delete(conv)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/chat/conversations/<int:cid>/messages', methods=['POST'])
@login_required
def send_chat_message(cid):
    conv = Conversation.query.filter_by(id=cid, user_id=session['user_id']).first()
    if not conv:
        return jsonify({'success': False, 'error': 'Conversa não encontrada'}), 404

    d = request.get_json()
    message = (d.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'Mensagem vazia'}), 400

    user = current_user()

    history = [m.to_dict() for m in conv.messages]

    system = (
        "Você é o TaskAI, um assistente de inteligência artificial integrado ao gerenciador de tarefas TaskAI.\n"
        f"Contexto atual:\n{build_ai_context(user)}\n\n"
        "Diretrizes:\n"
        "- Responda em português brasileiro (ou no idioma em que a pessoa escrever), de forma amigável e clara\n"
        "- Você pode conversar e ajudar com qualquer assunto, sem limite de tamanho: responda com o nível de detalhe que a pergunta pedir\n"
        "- Quando o assunto envolver tarefas, produtividade ou equipe, use o contexto acima\n"
        "- Se perguntarem a data ou hora, responda usando a data/hora informada no contexto acima\n"
        "- Não invente tarefas ou funcionários que não estão no contexto\n"
        "- Você não cria tarefas diretamente — oriente a pessoa a fazê-lo pela interface\n"
        "- Se a pessoa pedir um relatório, documento ou arquivo docx/word, informe que o relatório foi "
        "gerado e está disponível para download logo abaixo da sua resposta"
    )

    reply, err = call_groq(system, history, message)

    user_msg = ChatMessage(conversation_id=conv.id, role='user', content=message)
    db.session.add(user_msg)

    if err:
        db.session.commit()
        return jsonify({'success': False, 'error': err})

    report_url = None
    if deve_gerar_relatorio(message) and user.can_report():
        scope = 'team' if user.account_type == 'corporativo' else 'me'
        report_url = f'/api/report/docx?scope={scope}'

    ai_msg = ChatMessage(conversation_id=conv.id, role='assistant', content=reply, report_url=report_url)
    db.session.add(ai_msg)

    if conv.title == 'Nova conversa':
        conv.title = message[:48] + ('…' if len(message) > 48 else '')
    conv.updated_at = datetime.utcnow()

    user.register_ai_message()
    db.session.commit()

    return jsonify({
        'success': True, 'response': reply, 'report_url': report_url,
        'ai_remaining': user.ai_remaining(),
    })

# ═══════════════════════════════ INIT ═════════════════════════════════════════

with app.app_context():
    try:
        db.create_all()
    except Exception as exc:   # outro worker pode ter criado as tabelas ao mesmo tempo
        db.session.rollback()
        app.logger.warning('create_all: %s', exc)
    db.engine.dispose()        # não compartilha conexões entre workers do gunicorn

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')
