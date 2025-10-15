import os, json, time, re
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# === Config de base ===
BASE_DIR = Path(__file__).resolve().parent
TENANTS_DIR = BASE_DIR / "tenants"
TENANTS_DIR.mkdir(parents=True, exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")  # libre: changeable
BRAND = os.getenv("BRAND_NAME", "Betty Immo")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@spectramedia.ai")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")  # à mettre en prod (Render/ngrok)

app = Flask(__name__, static_folder="static", template_folder="templates")

# === Helpers ===
def slugify(txt: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", txt.strip().lower()).strip("-")
    return s[:60] or f"tenant-{int(time.time())}"

def tenant_path(tenant_id: str) -> Path:
    return TENANTS_DIR / f"{tenant_id}.json"

def save_tenant(cfg: dict) -> str:
    tenant_id = cfg.get("tenant_id") or slugify(cfg.get("email", "client")) + f"-{int(time.time())}"
    cfg["tenant_id"] = tenant_id
    with open(tenant_path(tenant_id), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return tenant_id

def load_tenant(tenant_id: str) -> dict:
    p = tenant_path(tenant_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}

# === Routes ===
@app.get("/")
def home():
    return {"status": "ok", "brand": BRAND, "message": "Betty Immo service up"}

@app.post("/webhooks/gumroad")
def gumroad_webhook():
    """
    Reçoit l’event Gumroad (POST). Gère JSON et form-encoded.
    Attend au minimum: purchaser_email, full_name, product_name (+ custom_fields optionnels)
    """
    if request.is_json:
        data = request.get_json(force=True)
    else:
        data = request.form.to_dict(flat=True)

    email = data.get("purchaser_email") or data.get("email") or ""
    full_name = data.get("full_name") or data.get("purchaser_name") or "Client"
    product = data.get("product_name") or data.get("product") or "Betty Immo"
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

    provision_url = f"{PUBLIC_BASE_URL}/t/{tenant_id}"
    embed_url = f"{PUBLIC_BASE_URL}/static/embed.js"

    return jsonify({
        "ok": True,
        "tenant_id": tenant_id,
        "provision_url": provision_url,
        "embed_instructions": {
            "script": f"<script src='{embed_url}' data-tenant='{tenant_id}'></script>",
            "notes": "Ajoutez ce script sur votre site pour afficher le widget de chat.",
        }
    }), 200

@app.get("/t/<tenant_id>")
def tenant_chat(tenant_id):
    cfg = load_tenant(tenant_id)
    if not cfg:
        return ("Inconnu", 404)
    return render_template("index.html", tenant_id=tenant_id, cfg=cfg, brand=BRAND)

@app.post("/api/chat/<tenant_id>")
def api_chat(tenant_id):
    cfg = load_tenant(tenant_id)
    if not cfg:
        return jsonify({"error": "unknown tenant"}), 404

    user_msg = (request.json or {}).get("message", "")

    # Démo sans clé : message statique utile
    if not OPENAI_API_KEY:
        reply = (
            f"Bonjour, ici {BRAND}. Comment puis-je vous aider ? "
            f"(Démo sans LLM — activez OPENAI_API_KEY pour des réponses enrichies)."
        )
        return jsonify({"reply": reply})

    # Exemple OpenAI (remplace par Together/Groq si souhaité)
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
        return jsonify({"reply": f"[fallback] Merci pour votre message. Nous revenons vers vous rapidement. ({e})"})

@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
