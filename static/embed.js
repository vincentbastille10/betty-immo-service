(function(){
  // Récupère le tenant à partir de l'attribut data-tenant du <script>
  const currentScript = document.currentScript || (function(){
    const scripts = document.getElementsByTagName('script');
    return scripts[scripts.length - 1];
  })();
  const TENANT = currentScript.getAttribute('data-tenant');
  if(!TENANT){ console.warn('[Betty] data-tenant manquant'); return; }

  // Base URL (domaine où est servi embed.js)
  const scriptSrc = new URL(currentScript.src);
  const BASE = scriptSrc.origin; // ex: https://betty-immo-service.onrender.com

  // Styles minimalistes
  const style = document.createElement('style');
  style.textContent = `
    .betty-widget-btn{
      position:fixed; right:18px; bottom:18px; z-index:2147483647;
      width:56px; height:56px; border-radius:50%;
      background:#11162a; color:#e5e7eb; border:1px solid rgba(255,255,255,.18);
      display:grid; place-items:center; cursor:pointer; box-shadow:0 8px 24px rgba(0,0,0,.4);
      font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial; font-size:14px;
    }
    .betty-iframe{
      position:fixed; right:18px; bottom:86px; z-index:2147483646;
      width: min(380px, 92vw); height: min(70vh, 540px);
      border:1px solid rgba(255,255,255,.18); border-radius:16px; overflow:hidden; display:none;
      box-shadow:0 12px 36px rgba(0,0,0,.45);
    }
  `;
  document.head.appendChild(style);

  // Bouton
  const btn = document.createElement('button');
  btn.className = 'betty-widget-btn';
  btn.title = 'Discuter avec Betty';
  btn.innerHTML = '💬';
  document.body.appendChild(btn);

  // Iframe → charge la page /t/<tenant_id>
  const frame = document.createElement('iframe');
  frame.className = 'betty-iframe';
  frame.src = `${BASE}/t/${TENANT}`;
  frame.allow = 'clipboard-read; clipboard-write';
  frame.referrerPolicy = 'no-referrer-when-downgrade';
  document.body.appendChild(frame);

  let open = false;
  btn.addEventListener('click', ()=>{
    open = !open;
    frame.style.display = open ? 'block' : 'none';
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
})();
