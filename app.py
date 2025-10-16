import os, json, time, re, smtplib, logging, hmac, hashlib
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory, abort

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

OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")
MODEL            = os.getenv("LLM_MODEL", "gpt-4o-mini")
BRAND            = os.getenv("BRAND_NAME", "Betty")
SUPPORT_EMAIL    = os.getenv("SUPPORT_EMAIL", "support@spectramedia.ai")
PUBLIC_BASE_URL  = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")

# Webhook security (optionnel) — mettre la même clé secrète dans Gumroad
GUMROAD_SECRET   = os.getenv("GUMROAD_WEBHOOK_SECRET", "")
VERIFY_SIGNATURE = bool(GUMROAD_SECRET)

# SMTP (optionnel)
SMTP_HOST       = os.getenv("SMTP_HOST", "")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASS       = os.getenv("SMTP_PASS", "")
SMTP_FROM       = os.getenv("SMTP_FROM", SMTP_USER or SUPPORT_EMAIL)
SMTP_FROM_NAME  = os.getenv("SMTP_FROM_NAME", BRAND)

app = Flask(__name__, static_folder="static", template_folder="templates")
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def slugify(txt: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (txt or "").strip().lower()).strip("-")
    return s[:60] or f"tenant-{int(time.time())}"

def tpath(tenant_id: str) -> Path:
    return TENANTS_DIR / f"{tenant_id}.json"

def read_tenant(tenant_id: str) -> dict:
    p = tpath(tenant_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}

def save_tenant(cfg: dict) -> str:
    """
    Crée ou met à jour un tenant. Si tenant_id fourni, on merge.
    """
    tenant_id = cfg.get("tenant_id") or f"{slugify(cfg.get('email', 'client'))}-{int(time.time())}"
    p = tpath(tenant_id)
    base = {}
    if p.exists():
        try:
            base = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            base = {}
    base.update(cfg)
    base["tenant_id"] = tenant_id
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    return tenant_id

def send_email(to_email: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
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

def boolish(v):
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def verify_gumroad_signature(raw_body: bytes) -> bool:
    """
    Gumroad peut envoyer X-Gumroad-Signature = HMAC-SHA256(body, secret)
    """
    if not VERIFY_SIGNATURE:
        return True
    try:
        sig = request.headers.get("X-Gumroad-Signature", "")
        mac = hmac.new(GUMROAD_SECRET.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, mac)
    except Exception:
        return False

def compute_subscription_status(payload: dict) -> dict:
    """
    Normalise l'état d'abonnement à partir du webhook Gumroad (vente unique ou récurrente).
    On reste robuste aux variations de clés.
    """
    refunded       = boolish(payload.get("refunded") or payload.get("is_refunded") or "false")
    disputed       = boolish(payload.get("disputed") or payload.get("is_disputed") or "false")
    chargeback     = boolish(payload.get("chargebacked") or payload.get("is_chargebacked") or "false")
    cancelled      = boolish(payload.get("cancelled") or payload.get("canceled") or payload.get("subscription_cancelled") or "false")
    recurrence     = (payload.get("recurrence") or payload.get("subscription_duration") or "").lower()  # e.g. "monthly"
    is_recurring   = boolish(payload.get("is_recurring_charge") or (recurrence != ""))  # approx
    subscription_id= payload.get("subscription_id") or payload.get("subscription") or ""
    order_id       = payload.get("order_id") or payload.get("sale_id") or payload.get("id") or ""
    status_text    = (payload.get("status") or "").lower()  # sometimes "paid", "failed", etc.

    paid_ok = (status_text in {"paid", "success"} or True) and not (refunded or disputed or chargeback)
    # Règle d'activité :
    # - si recurring: actif si payé_ok ET non cancelled
    # - si one-shot: actif si payé_ok (accès à vie ou période définie côté produit)
    active = (paid_ok and (not cancelled))

    return {
        "active": bool(active),
        "refunded": bool(refunded),
        "disputed": bool(disputed),
        "chargebacked": bool(chargeback),
        "cancelled": bool(cancelled),
        "recurrence": recurrence,              # "monthly", "yearly", ...
        "is_recurring": bool(is_recurring),
        "subscription_id": subscription_id,
        "order_id": order_id,
        "raw_status": status_text,
        "updated_at": int(time.time()),
    }

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

@app.get("/tenants/<tenant_id>")
def get_tenant(tenant_id):
    cfg = read_tenant(tenant_id)
    if not cfg:
        return jsonify({"error": "unknown tenant"}), 404
    return jsonify(cfg)

# -------- Webhook GUMROAD (achat / renouvellement / annulation / refund) --------
@app.post("/webhooks/gumroad")
def gumroad_webhook():
    try:
        raw = request.get_data()  # bytes for signature
        if not verify_gumroad_signature(raw):
            app.logger.error("❌ Signature Gumroad invalide")
            return jsonify({"error": "invalid signature"}), 401

        # JSON ou x-www-form-urlencoded
        data = request.get_json(silent=True) or request.form.to_dict(flat=True)
        app.logger.info("--- Nouveau webhook Gumroad ---")
        app.logger.info(json.dumps(data, indent=2))
        print("\033[94m--- Nouveau webhook Gumroad reçu ---\033[0m")
        print(json.dumps(data, indent=2))

        email     = data.get("purchaser_email") or data.get("email") or ""
        full_name = data.get("full_name") or data.get("purchaser_name") or "Client"
        product   = data.get("product_name") or data.get("product") or BRAND
        website   = data.get("custom_fields[website]") or data.get("website") or ""
        company   = data.get("custom_fields[company]") or data.get("company") or ""
        # Permet au même client d’être updaté au même tenant si déjà créé
        tenant_id_hint = slugify(email) if email else None

        sub_state = compute_subscription_status(data)

        cfg = {
            "email": email,
            "full_name": full_name,
            "product": product,
            "website": website,
            "company": company,
            "brand": BRAND,
            "subscription": sub_state,
            "gumroad_raw": data,  # utile pour debug Render
        }

        if tenant_id_hint:
            cfg["tenant_id"] = tenant_id_hint  # on stabilise l'ID si même email

        tenant_id = save_tenant(cfg)

        # URLs utiles
        provision_url = f"{PUBLIC_BASE_URL}/t/{tenant_id}"
        embed_url     = f"{PUBLIC_BASE_URL}/static/embed.js"
        script_tag    = f"<script src='{embed_url}' data-tenant='{tenant_id}'></script>"

        # Email d’onboarding / mise à jour (optionnel)
        subject = f"Votre assistante {BRAND} – accès {'activé' if sub_state['active'] else 'mis à jour'}"
        status_line = "✅ Abonnement actif" if sub_state["active"] else "⏸️ Abonnement inactif (annulé ou non payé)"
        html = f"""
        <!doctype html>
        <html lang="fr"><head><meta charset="utf-8"></head>
        <body style="font-family:Arial,Helvetica,sans-serif;color:#1a1f36;">
          <h2>Bonjour {full_name} 👋</h2>
          <p>Produit : <b>{product}</b></p>
          <p><b>{status_line}</b></p>
          <p>Espace : <a href="{provision_url}" target="_blank">{provision_url}</a></p>
          <p>Script d’intégration :</p>
          <pre style="background:#0b1020;color:#e5e7eb;padding:12px;border-radius:8px;white-space:pre-wrap">{script_tag}</pre>
          <p>Support : {SUPPORT_EMAIL}</p>
        </body></html>
        """
        text = (
            f"Bonjour {full_name},\n\n"
            f"Produit : {product}\n"
            f"Statut : {'actif' if sub_state['active'] else 'inactif'}\n"
            f"Espace : {provision_url}\n\n"
            f"Script : {script_tag}\n\n"
            f"Support : {SUPPORT_EMAIL}\n"
        )
        # envoie même si pas d'email client → tombe sur SUPPORT_EMAIL pour log
        send_email(email or SUPPORT_EMAIL, subject, html, text)

        print(f"\033[92m✅ Webhook traité (tenant_id={tenant_id}, actif={sub_state['active']})\033[0m")
        app.logger.info(f"✅ Webhook traité (tenant_id={tenant_id}, actif={sub_state['active']})")

        return jsonify({
            "ok": True,
            "tenant_id": tenant_id,
            "active": sub_state["active"],
            "provision_url": provision_url,
            "embed_instructions": {
                "script": script_tag,
                "notes": "Ajoutez ce script avant </body> sur votre site."
            }
        }), 200

    except Exception as e:
        print(f"\033[91m❌ Erreur webhook Gumroad : {e}\033[0m")
        app.logger.error(f"❌ Erreur webhook Gumroad : {e}")
        return jsonify({"error": str(e)}), 400

# -------- UI & API --------
@app.get("/t/<tenant_id>")
def tenant_chat(tenant_id):
    cfg = read_tenant(tenant_id)
    if not cfg:
        return ("Inconnu", 404)

    # Blocage si abonnement inactif
    sub = (cfg.get("subscription") or {})
    if not sub.get("active", False):
        return (
            f"<h2>{BRAND}</h2><p>Accès inactif pour ce compte."
            f" Veuillez renouveler votre abonnement pour réactiver l'assistante.</p>", 402
        )
    return render_template("index.html", tenant_id=tenant_id, cfg=cfg, brand=BRAND)

@app.post("/api/chat/<tenant_id>")
def api_chat(tenant_id):
    cfg = read_tenant(tenant_id)
    if not cfg:
        return jsonify({"error": "unknown tenant"}), 404

    # Vérifie l'état d'abonnement
    sub = (cfg.get("subscription") or {})
    if not sub.get("active", False):
        return jsonify({"error": "subscription_inactive", "reply": "Abonnement inactif. Merci de renouveler."}), 402

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
