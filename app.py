import os, json, time, re, smtplib, logging
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory

# --------------------------------------------------------------------
# .env local (ignorer en prod si non présent)
# --------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
TENANTS_DIR = BASE_DIR / "tenants"
TENANTS_DIR.mkdir(parents=True, exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
BRAND = os.getenv("BRAND_NAME", "Betty Immo")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@spectramedia.ai")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")

# SMTP (optionnel — si non renseigné, on n’enverra pas d’email)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or SUPPORT_EMAIL)
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", BRAND)

app = Flask(__name__, static_folder="static", template_folder="templates")

# Logs visibles dans Render
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def slugify(txt: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (txt or "").strip().lower()).strip("-")
    return s[:60] or f"tenant-{int(time.time())}"

def tenant_path(tenant_id: str) -> Path:
    return TENANTS_DIR / f"{tenant_id}.json"

def save_tenant(cfg: dict) -> str:
    tenant_id = cfg.get("tenant_id") or f"{slugify(cfg.get('email', 'client'))}-{int(time.time())}"
    cfg["tenant_id"] = tenant_id
    tenant_path(tenant_id).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return tenant_id

def load_tenant(tenant_id: str) -> dict:
    p = tenant_path(tenant_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}

def send_email(to_email: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """Envoi SMTP simple — si non configuré, on log et on n’interrompt pas le flux."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and to_email and SMTP_FROM):
        app.logger.warning("SMTP non configuré ou destinataire vide — email non envoyé.")
        return False
    msg = MIMEText(text_body or html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM))
    msg["To"] = to_email
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        app.logger.info(f"📧 Email envoyé à {to_email}")
        return True
    except Exception as e:
        app.logger.error(f"❌ Erreur envoi email: {e}")
        return False

# --------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------
@app.get("/")
def home():
    return {"status": "ok", "brand": BRAND, "message": f"{BRAND} service up"}

@app.get("/tenants")
def list_tenants():
    files = sorted(p.name for p in TENANTS_DIR.glob("*.json"))
    return jsonify({"count": len(files), "files": files})

# Webhook Gumroad (unique)
@app.post("/webhooks/gumroad")
def gumroad_webhook():
    """
    Reçoit l’événement Gumroad (POST), enregistre le client (/tenants),
    envoie l’email d’onboarding si SMTP configuré, et retourne les instructions d’intégration.
    """
    try:
        # Récupération données JSON ou form-encoded
        data = request.get_json(force=True) if request.is_json else request.form.to_dict(flat=True)

        app.logger.info("--- Nouveau webhook Gumroad reçu ---")
        app.logger.info(json.dumps(data, indent=2))
        print("\033[94m--- Nouveau webhook Gumroad reçu ---\033[0m")
        print(json.dumps(data, indent=2))

        email = data.get("purchaser_email") or data.get("email") or ""
        full_name = data.get("full_name") or data.get("purchaser_name") or "Client"
        product = data.get("product_name") or data.get("product") or BRAND
        website = data.get("custom_fields[website]") or data.get("website") or ""
        company = data.get("custom_fields[company]") or data.get("company") or ""

        cfg = {
            "email": email,
            "full_name": full_name,
            "product": product,
            "website": website,
            "company": company,
            "created_at": int(time.time()),
            "brand": BRAND,
        }

        tenant_id = save_tenant(cfg)

        # URLs utiles
        provision_url = f"{PUBLIC_BASE_URL}/t/{tenant_id}"
        embed_url = f"{PUBLIC_BASE_URL}/static/embed.js"
        script_tag = f"<script src='{embed_url}' data-tenant='{tenant_id}'></script>"

        # Email d’onboarding (optionnel)
        subject = f"Votre assistante {BRAND} est prête 🎉"
        html = f"""
        <!doctype html>
        <html lang="fr">
          <head><meta charset="utf-8"></head>
          <body style="font-family:Arial,Helvetica,sans-serif;color:#1a1f36;">
            <h2>Bienvenue {full_name} 👋</h2>
            <p>Merci pour votre achat <b>{product}</b>. Votre espace est prêt :</p>
            <p><a href="{provision_url}" target="_blank">Ouvrir mon espace</a></p>
            <p>À intégrer sur votre site :</p>
            <pre style="background:#0b1020;color:#e5e7eb;padding:12px;border-radius:8px;white-space:pre-wrap">{script_tag}</pre>
            <p>Besoin d’aide ? {SUPPORT_EMAIL}</p>
          </body>
        </html>
        """
        text = (
            f"Bonjour {full_name},\n\n"
            f"Votre espace {BRAND} est prêt : {provision_url}\n\n"
            f"Script d’intégration :\n{script_tag}\n\n"
            f"Support : {SUPPORT_EMAIL}\n"
        )
        send_email(email or SUPPORT_EMAIL, subject, html, text)

        # Logs verts Render (ANSI) + logs classiques
        print(f"\033[92m✅ Webhook reçu et sauvegardé pour {email} (tenant_id={tenant_id})\033[0m")
        app.logger.info(f"✅ Webhook reçu et sauvegardé pour {email} (tenant_id={tenant_id})")

        return jsonify({
            "ok": True,
            "tenant_id": tenant_id,
            "provision_url": provision_url,
            "embed_instructions": {
                "script": script_tag,
                "notes": "Ajoutez ce script sur votre site (avant </body>) pour afficher le widget."
            }
        }), 200

    except Exception as e:
        print(f"\033[91m❌ Erreur webhook Gumroad : {e}\033[0m")
        app.logger.error(f"❌ Erreur webhook Gumroad : {e}")
        return jsonify({"error": str(e)}), 400

@app.get("/t/<tenant_id>")
def tenant_chat(tenant_id):
    cfg = load_tenant(tenant_id)
    if not cfg:
        return ("Inconnu", 404)
    # nécessite templates/index.html
    return render_template("index.html", tenant_id=tenant_id, cfg=cfg, brand=BRAND)

@app.post("/api/chat/<tenant_id>")
def api_chat(tenant_id):
    cfg = load_tenant(tenant_id)
    if not cfg:
        return jsonify({"error": "unknown tenant"}), 404

    user_msg = (request.json or {}).get("message", "")

    if not OPENAI_API_KEY:
        reply = (
            f"Bonjour, ici {BRAND}. Comment puis-je vous aider ? "
            f"(Démo sans LLM — activez OPENAI_API_KEY pour des réponses enrichies)."
        )
        return jsonify({"reply": reply})

    try:
        import requests
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        body = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": f"Tu es {BRAND}, assistante d'un site immobilier. Réponds de façon concise et utile."},
                {"role": "user", "content": user_msg}
            ]
        }
        r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        reply = data["choices"][0]["message"]["content"].strip()
        return jsonify({"reply": reply})
    except Exception as e:
        app.logger.error(f"LLM error: {e}")
        return jsonify({"reply": "[fallback] Merci pour votre message. Nous revenons vers vous rapidement."})

@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

# --------------------------------------------------------------------
# Entrée
# --------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
