# Service Flask – Provision & Chat


## Local
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env # remplir PUBLIC_BASE_URL si vous utilisez ngrok/Render
python app.py


## Test webhook (local)
# 1) Lancer le serveur, puis exposer en public (ex. ngrok http 5000)
# 2) Envoyer un POST (JSON) :
curl -X POST "$PUBLIC_BASE_URL/webhooks/gumroad" \
-H 'Content-Type: application/json' \
-d '{
"purchaser_email":"client@example.com",
"full_name":"Marie Client",
"product_name":"Betty Immo",
"website":"https://agence-dupont.fr",
"company":"Agence Dupont"
}'


# Réponse: tenant_id + URL de chat + snippet <script>