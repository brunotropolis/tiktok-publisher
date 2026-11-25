"""
Posta um CARROSSEL DE FOTOS no TikTok via sessionid (aba "Fotos" do TikTok Studio web).
Uso:
  python run_photos.py <lista.json> "<legenda>" [only_you|everyone|friends] [headless|headed]
  lista.json = ["caminho1.png", "caminho2.png", ...]  (ate 35, ordem = ordem no carrossel)
Env:
  TT_SESSIONID_MRN  sessionid da conta (o server.py passa a sessao da conta pedida por aqui)
  TT_SOM            opcional: termo de busca do som. Sem ele usa a 1a sugestao "For You" do TikTok
                    (o TikTok sugere sons populares que combinam com as fotos). TT_SOM=nenhum = sem som.
Saida: imprime ">> som: <nome>" quando escolhe som. Exit 0 = formulario submetido.
A VERIFICACAO de verdade (apareceu no Studio, privacidade certa) e feita pelo publicar_tiktok.py.
Nunca imprime o sessionid.
"""
import sys, os, json, time, pathlib
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
VIS = {"everyone": "Everyone", "friends": "Friends", "only_you": "Only you"}
HERE = pathlib.Path(__file__).parent


def load_sid():
    s = os.environ.get("TT_SESSIONID_MRN")
    if s:
        return s.strip()
    p = HERE / ".session_mrn"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    sys.exit("ERRO: sem sessionid")


def kill_overlays(page):
    try:
        page.evaluate("""() => {
          document.querySelectorAll('[role="dialog"], .TUXModal').forEach(d => {
            if (!d.offsetParent || /Sounds/.test(d.innerText||'')) return;
            const b=[...d.querySelectorAll('button')].filter(x=>x.offsetParent)
              .find(x=>/^(cancel|got it|ok|skip|dismiss|no thanks|maybe later|not now)$/i.test((x.innerText||'').trim()));
            if (b) b.click();
          });
          // NAO remover elementos do DOM aqui: derruba o React do Studio ("Something went wrong")
        }""")
    except Exception:
        pass


def titulo_de(legenda):
    """Titulo (max 90): 1a linha da legenda, sem hashtags."""
    linha = next((l.strip() for l in legenda.splitlines() if l.strip()), "")
    linha = " ".join(w for w in linha.split() if not w.startswith("#"))
    return linha[:90]


def escolher_som(page, termo):
    if (termo or "").strip().lower() == "nenhum":
        print(">> som: (sem som, pedido)")
        return None
    page.get_by_role("button", name="Add sound").click()
    page.wait_for_selector("text=For You", timeout=20000)
    time.sleep(3)
    if termo:
        page.get_by_placeholder("Search sounds").fill(termo)
        page.keyboard.press("Enter")
        time.sleep(5)
    # 1o item da lista com botao "Use": pega o nome antes de clicar
    info = page.evaluate("""() => {
      const use=[...document.querySelectorAll('button')].filter(b=>b.offsetParent && (b.innerText||'').trim()==='Use');
      if(!use.length) return null;
      let row=use[0]; for(let i=0;i<6 && row;i++){ row=row.parentElement; if(row && (row.innerText||'').split('\\n').length>=3) break; }
      const r=use[0].getBoundingClientRect();
      return {nome:(row?row.innerText:'').split('\\n').filter(Boolean).slice(0,2).join(' | '), x:r.x+r.width/2, y:r.y+r.height/2};
    }""")
    if not info:
        print(">> som: nenhuma sugestao encontrada, seguindo sem som")
        page.keyboard.press("Escape")
        return None
    page.mouse.click(info["x"], info["y"])
    time.sleep(4)
    # fecha o modal de sons se ainda estiver aberto
    page.evaluate("""() => { const d=[...document.querySelectorAll('[role=dialog], .TUXModal, [class*=Modal]')].find(e=>e.offsetParent && /Sounds/.test(e.innerText||''));
      if(d){ const x=d.querySelector('button[aria-label], [class*=close]'); if(x) x.click(); } }""")
    time.sleep(1)
    print(f">> som: {info['nome']}")
    return info["nome"]


def vis_label(page):
    return page.evaluate("""() => { const b=document.querySelector("div[data-e2e='video_visibility_container'] button[role='combobox']"); return b?(b.innerText||'').trim():null; }""")


def set_vis(page, vis):
    want = VIS.get(vis, "Everyone")
    for _ in range(6):
        kill_overlays(page)
        page.evaluate("""() => { const b=document.querySelector("div[data-e2e='video_visibility_container'] button[role='combobox']"); if(b) b.click(); }""")
        time.sleep(1.2)
        page.evaluate("""(w) => { const o=[...document.querySelectorAll("[role='option']")].find(e=>(e.innerText||'').trim().toLowerCase().startsWith(w.toLowerCase())); if(o) o.click(); }""", want)
        time.sleep(1)
        got = vis_label(page)
        print(f">> privacidade: {got!r}")
        if got and want.lower() in got.lower():
            return True
    return False


def publish(fotos, legenda, vis="only_you", headless=True):
    fotos = [str(pathlib.Path(f).resolve()) for f in fotos]
    for f in fotos:
        if not os.path.exists(f):
            raise FileNotFoundError(f)
    if not 1 <= len(fotos) <= 35:
        raise ValueError("carrossel precisa de 1 a 35 fotos")
    sid = load_sid()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        ctx = b.new_context(user_agent=UA, viewport={"width": 1440, "height": 900}, locale="en-US")
        ctx.add_cookies([{"name": "sessionid", "value": sid, "domain": ".tiktok.com", "path": "/",
                          "httpOnly": True, "secure": True, "sameSite": "None"}])
        page = ctx.new_page()
        try:
            page.goto("https://www.tiktok.com/tiktokstudio/upload?tab=photo", wait_until="domcontentloaded")
            page.wait_for_selector("input[type=file]", state="attached", timeout=60000)
            time.sleep(3)
            page.locator("input[type=file]").first.set_input_files(fotos)
            # espera as fotos subirem ("N photos uploaded")
            for _ in range(60):
                t = page.evaluate("document.body.innerText")
                if f"{len(fotos)} photos uploaded" in t or (len(fotos) == 1 and "photo uploaded" in t):
                    break
                time.sleep(2)
            else:
                raise RuntimeError("fotos nao terminaram de subir")
            print(f">> {len(fotos)} fotos carregadas")
            time.sleep(2)
            kill_overlays(page)

            # titulo + descricao
            # (fill() no titulo e Ctrl+A/Delete na descricao QUEBRAM a pagina: "Something went wrong")
            tit = titulo_de(legenda)
            if tit:
                page.locator("div[data-e2e='caption_container'] input").first.click()
                page.keyboard.type(tit, delay=12)
                time.sleep(0.5)
            page.locator("div[data-e2e='caption_container'] [contenteditable='true']").first.click()
            time.sleep(0.5)
            linhas = legenda[:3900].split("\n")
            for i, l in enumerate(linhas):
                if l:
                    page.keyboard.type(l, delay=8)
                    if "#" in l or "@" in l:
                        page.keyboard.type(" ", delay=8)  # fecha sugestao de hashtag/mencao
                        time.sleep(1)
                if i < len(linhas) - 1:
                    page.keyboard.press("Shift+Enter")
            time.sleep(1.5); page.keyboard.press("Escape")
            if "Something went wrong" in page.evaluate("document.body.innerText"):
                raise RuntimeError("pagina do TikTok quebrou ao escrever a legenda")
            print(">> legenda ok")
            if os.environ.get("TT_DEBUG"): page.screenshot(path=str(HERE/"_dbg_legenda.png"))

            # som
            try:
                escolher_som(page, os.environ.get("TT_SOM", ""))
            except Exception as e:
                print(f">> som falhou ({str(e)[:80]}), seguindo sem som")
                page.keyboard.press("Escape")

            # privacidade (trava: so posta se confirmar)
            if not set_vis(page, vis):
                raise RuntimeError("ABORT DE SEGURANCA: nao confirmei a privacidade, NAO postei")
            want = VIS.get(vis, "Everyone")
            if want.lower() not in (vis_label(page) or "").lower():
                raise RuntimeError("ABORT DE SEGURANCA: privacidade mudou antes de postar")

            # postar
            kill_overlays(page)
            btn = page.get_by_role("button", name="Post", exact=True).first
            btn.scroll_into_view_if_needed()
            time.sleep(1)
            btn.click()
            for _ in range(30):
                time.sleep(1)
                # modal de confirmacao (ex.: "Post now")
                page.evaluate("""() => { const g=[...document.querySelectorAll('[role=dialog] button, .TUXModal button')].filter(b=>b.offsetParent).find(b=>/^(post|post now|publish|confirm)$/i.test((b.innerText||'').trim())); if(g) g.click(); }""")
                if "/upload" not in page.url or not page.get_by_role("button", name="Post", exact=True).count():
                    print(">> POST submetido")
                    return True
            page.screenshot(path=str(HERE / "_fotos_falha.png"))
            print("!! nao confirmei a saida do formulario")
            return False
        finally:
            b.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    lista = json.load(open(sys.argv[1], encoding="utf-8"))
    vis = sys.argv[3] if len(sys.argv) > 3 else "only_you"
    hl = (sys.argv[4] if len(sys.argv) > 4 else "headless") == "headless"
    sys.exit(0 if publish(lista, sys.argv[2], vis, hl) else 1)
