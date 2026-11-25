"""
Responde DMs do TikTok por palavra-chave (rota cookie, igual ao publicador). 25/Nov, teste no @buscador_geek.
Abre tiktok.com/messages, olha as SOLICITACOES e as conversas; se a ULTIMA mensagem da conversa (a previa da
lista) for exatamente uma palavra-chave conhecida, aceita a solicitacao (se for) e responde com o texto dela.
Idempotente: depois que a gente responde, a previa vira a nossa resposta e a conversa nao casa mais.

Uso:
  python dm_responder.py <palavras.json> [max_respostas=8] [headless|headed]
  palavras.json = {"RICA": "texto da resposta com os links", "FORCA": "..."}
Env: TT_SESSIONID_MRN (sessao da conta; o server.py passa a da conta pedida)
Saida: ultima linha = JSON {"ok":true,"respondidas":[{"usuario","palavra"}],"vistas":N}
STATUS 25/Nov: NAO LIGADO. No teste, o TikTok bloqueou TODA mensagem enviada pelo @buscador_geek (ate "oi" digitado na
mao no Chrome normal): "Esta mensagem pode estar violando nossas Diretrizes... nao foi enviada". Restricao da conta
(nova, sem historico), nao do robo. Retestar quando a conta tiver historico; o robo para sozinho se vir esse aviso.
Gotcha: o data-e2e 'dm-new-stranger-accept' e o QUADRO da solicitacao; clicar no centro dele aperta "Excluir".
"""
import sys, os, json, time, re, unicodedata, pathlib
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HERE = pathlib.Path(__file__).parent


def norm(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", t.upper())


def itens(page):
    """Conversas visiveis na lista: [{i, nome, previa}]."""
    return page.evaluate("""() => [...document.querySelectorAll("[data-e2e='dm-new-conversation-item']")].map((e,i)=>{
      const nome=(e.querySelector("[data-e2e='dm-new-conversation-nickname']")||{}).innerText||'';
      const linhas=(e.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean);
      // previa = linha depois do nome que nao e hora/data
      const prev=linhas.filter(l=>l!==nome.trim() && !/^\\d{1,2}:\\d{2}$|^\\d{1,2}-\\d{1,2}(-\\d{4})?$|^\\d+$/.test(l))[0]||'';
      return {i, nome:nome.trim(), previa:prev};
    })""")


def responder(page, idx, texto):
    page.locator("[data-e2e='dm-new-conversation-item']").nth(idx).click()
    time.sleep(4)
    usuario = page.evaluate("""() => ((document.querySelector("[data-e2e='chat-uniqueid']")||{}).innerText||'').trim()""")
    acc = page.locator("[data-e2e='dm-new-stranger-accept']")
    if acc.count() and acc.first.is_visible():
        # o data-e2e e o quadro inteiro; o botao e o filho com texto "Aceitar"
        # NUNCA clicar no quadro (o centro dele e o botao "Excluir"): so no botao com texto exato
        btn = acc.first.get_by_text(re.compile(r"^\s*(Aceitar|Accept)\s*$"))
        if not btn.count():
            raise RuntimeError("botao Aceitar nao encontrado")
        btn.last.click()
        time.sleep(5)
    dbg = os.environ.get("TT_DEBUG")
    if dbg: page.screenshot(path=str(HERE / "_dm1_aberta.png"))
    caixa = page.locator("[data-e2e='message-input-area'] [contenteditable='true'], div[contenteditable='true']").last
    caixa.click(); time.sleep(0.5)
    linhas = texto.split("\n")
    for i, l in enumerate(linhas):
        if l:
            page.keyboard.type(l, delay=6)
        if i < len(linhas) - 1:
            page.keyboard.press("Shift+Enter")
    time.sleep(0.8)
    if dbg: page.screenshot(path=str(HERE / "_dm2_digitada.png"))
    page.keyboard.press("Enter")
    time.sleep(4)
    if dbg: page.screenshot(path=str(HERE / "_dm3_enviada.png"))
    ult = page.evaluate("""() => { const m=[...document.querySelectorAll("[data-e2e='dm-new-message-text']")]; return m.length?(m[m.length-1].innerText||''):''; }""")
    # o TikTok mostra a mensagem localmente mesmo quando NAO envia: confere o aviso de bloqueio
    corpo = page.evaluate("document.body.innerText")
    if re.search(r"n[aã]o foi enviada|was not sent|violando nossas Diretrizes|violate our Community Guidelines", corpo, re.I):
        raise RuntimeError("BLOQUEADO: o TikTok nao enviou a resposta (aviso de Diretrizes da Comunidade). Parei o ciclo.")
    ok = norm(ult)[:20] == norm(texto)[:20]
    return usuario, ok


def ciclo(palavras, maxr=8, headless=True):
    sid = (os.environ.get("TT_SESSIONID_MRN") or "").strip()
    if not sid:
        raise SystemExit("sem sessao")
    mapa = {norm(k): (k, v) for k, v in palavras.items() if norm(k)}
    feitas, vistas, falhas = [], 0, []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        ctx = b.new_context(user_agent=UA, viewport={"width": 1440, "height": 900}, locale="pt-BR")
        ctx.add_cookies([{"name": "sessionid", "value": sid, "domain": ".tiktok.com", "path": "/",
                          "httpOnly": True, "secure": True, "sameSite": "None"}])
        page = ctx.new_page()
        try:
            for lista in ("solicitacoes", "conversas"):
                page.goto("https://www.tiktok.com/messages", wait_until="domcontentloaded")
                page.wait_for_selector("[data-e2e='dm-new-conversation-list']", timeout=60000)
                time.sleep(5)
                if lista == "solicitacoes":
                    sol = page.get_by_text("Solicitações de mensagem")
                    if not sol.count():
                        continue
                    sol.first.click(); time.sleep(4)
                for _ in range(maxr):
                    if len(feitas) >= maxr:
                        break
                    its = itens(page)
                    vistas = max(vistas, len(its))
                    alvo = next((it for it in its if norm(it["previa"]) in mapa and it["nome"] not in [f.get("nome") for f in falhas]), None)
                    if not alvo:
                        break
                    palavra, texto = mapa[norm(alvo["previa"])]
                    usuario, ok = responder(page, alvo["i"], texto)
                    print(f">> {lista}: {usuario or alvo['nome']} mandou {palavra} -> respondido={ok}")
                    (feitas if ok else falhas).append({"usuario": usuario, "nome": alvo["nome"], "palavra": palavra})
                    time.sleep(3)
        finally:
            b.close()
    return {"ok": True, "respondidas": feitas, "falhas": falhas, "vistas": vistas}


if __name__ == "__main__":
    pal = json.load(open(sys.argv[1], encoding="utf-8"))
    mx = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    hl = (sys.argv[3] if len(sys.argv) > 3 else "headless") == "headless"
    try:
        r = ciclo(pal, mx, hl)
    except Exception as e:
        r = {"ok": False, "reason": str(e)[:300]}
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r.get("ok") else 1)
