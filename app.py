import json
import os
import secrets
import tempfile
import threading
from pathlib import Path

from flask import Flask, jsonify, redirect, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-before-production")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RAILWAY_ENVIRONMENT") is not None,
)
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "gestion_fonds.db"))
INDEX_PATH = Path(__file__).with_name("index.html")
STATE_LOCK = threading.Lock()
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

LOGIN_PAGE = """<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Connexion — Gestion de Fonds</title><style>body{font-family:system-ui;background:#07111f;color:#eef4ff;display:grid;place-items:center;min-height:100vh;margin:0}.card{width:min(88vw,380px);background:#101d30;padding:28px;border-radius:18px;box-shadow:0 18px 60px #0008}h1{margin-top:0}input,button{box-sizing:border-box;width:100%;padding:13px;border-radius:10px;margin-top:12px;font-size:16px}input{background:#07111f;color:white;border:1px solid #50617a}button{background:#28c3a9;border:0;font-weight:700;color:#06150f}.error{color:#ff9d9d}</style></head><body><form class=\"card\" method=\"post\" action=\"/login\"><h1>Gestion de Fonds</h1><p>Entrez votre mot de passe.</p>{error}<input type=\"password\" name=\"password\" required autofocus autocomplete=\"current-password\"><button type=\"submit\">Se connecter</button></form></body></html>"""


def read_state():
    try:
        state = json.loads(DATABASE_PATH.read_text(encoding="utf-8"))
        if isinstance(state.get("accounts"), list) and isinstance(state.get("transactions"), list):
            return state
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        pass
    return None


def write_state(state):
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=DATABASE_PATH.parent, prefix="gestion_fonds_", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(state, temporary_file, ensure_ascii=False, separators=(",", ":"))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, DATABASE_PATH)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


@app.before_request
def require_login():
    if request.path in {"/health", "/login"}:
        return None
    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify(error="Non autorisé"), 401
        return redirect("/login")
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if APP_PASSWORD and secrets.compare_digest(supplied, APP_PASSWORD):
            session.clear()
            session["authenticated"] = True
            return redirect("/")
        error = '<p class="error">Mot de passe incorrect.</p>'
    return LOGIN_PAGE.format(error=error), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/")
def index():
    html = INDEX_PATH.read_text(encoding="utf-8")
    state = read_state()
    if state is not None:
        encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        html = html.replace("</head>", f"<script>window.__INITIAL_STATE__={encoded}</script></head>")
    return html, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/api/state")
def get_state():
    return jsonify(read_state() or {"accounts": [], "transactions": []})


@app.put("/api/state")
def put_state():
    state = request.get_json(silent=True)
    if not isinstance(state, dict) or not isinstance(state.get("accounts"), list) or not isinstance(state.get("transactions"), list):
        return jsonify(error="Données invalides"), 400
    with STATE_LOCK:
        write_state(state)
    return jsonify(saved=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "3000")))
