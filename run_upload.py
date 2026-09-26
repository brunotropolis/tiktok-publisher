"""
Posta um video no TikTok via sessionid (rota nao-oficial: dirige a pagina de upload).
Uso:
  python run_upload.py <video.mp4> "<legenda>" [only_you|everyone] [headless|headed]
O sessionid e lido de .session_mrn (uma linha) OU da env TT_SESSIONID_MRN.
Nunca imprime o sessionid.
"""
import sys, os, pathlib

def load_sessionid():
    env = os.environ.get("TT_SESSIONID_MRN")
    if env:
        return env.strip()
    p = pathlib.Path(__file__).with_name(".session_mrn")
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    sys.exit("ERRO: sem sessionid (.session_mrn ou TT_SESSIONID_MRN)")

def publish(video, desc, visibility="only_you", headless=True, sessionid=None):
    """Posta 1 video. Retorna True se o upload_video nao reportou falha (a VERIFICACAO
    de verdade e feita pelo publicar_tiktok.py, que confere no Studio)."""
    if not os.path.exists(video):
        raise FileNotFoundError(f"video nao encontrado: {video}")

    from tiktok_uploader import upload as up
    from tiktok_uploader.upload import upload_video
    import time as _t

    VIS_LABEL = {"everyone": "Everyone", "friends": "Friends", "only_you": "Only you"}
    REQUIRED_LABEL = VIS_LABEL.get(visibility, "Everyone")

    def _kill_overlays(page):
        # 1) fecha modais/coachmarks: content-check (Cancel), editing-features (Got it), etc.
        try:
            page.evaluate("""() => {
              const clickIn = (root) => {
                const btns=[...root.querySelectorAll('button')].filter(b=>b.offsetParent);
                let b = btns.find(x=>/^(cancel|got it|ok|skip|next|dismiss|no thanks|maybe later)$/i.test((x.innerText||'').trim()))
                     || root.querySelector('button[aria-label]');
                if(b){ try{b.click();}catch(_){}; return true; }
                return false;
              };
              document.querySelectorAll('[role="dialog"], .TUXModal, [data-floating-ui-portal]').forEach(d=>{ if(d.offsetParent) clickIn(d); });
            }""")
        except Exception:
            pass
        # 2) remove o que sobrar de tooltip/coachmark flutuante
        try:
            page.evaluate("""() => {
              document.querySelectorAll('[data-floating-ui-portal]').forEach(e=>{try{e.remove()}catch(_){}});
              document.querySelectorAll('[class*="Tooltip"],[class*="tooltip"],[class*="Coach"],[class*="coach"]').forEach(e=>{try{e.remove()}catch(_){}});
            }""")
        except Exception:
            pass

    def _vis_label(page):
        return page.evaluate("""() => {
          const b = document.querySelector("div[data-e2e='video_visibility_container'] button[role='combobox']");
          return b ? (b.innerText||'').trim() : null;
        }""")

    # --- PATCH legenda: foco via DOM + digita no teclado (clique normal e interceptado) ---
    def _set_description_fixed(page, description, *a, **k):
        try:
            print(">> [patch] setando legenda")
            _kill_overlays(page)
            page.evaluate("""() => {
              const e = document.querySelector("div[data-e2e='caption_container'] div[contenteditable='true']")
                     || document.querySelector("div[contenteditable='true']");
              if (e) e.focus();
            }""")
            _t.sleep(0.3)
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.keyboard.type(description, delay=15)
            _t.sleep(1)
        except Exception as e:
            print(f">> [patch] aviso legenda: {e}")

    # --- PATCH privacidade: abre + escolhe via DOM click (o unico que funciona), CONFERE ---
    def _set_visibility_fixed(page, vis):
        want = VIS_LABEL.get(vis, "Everyone")
        print(f">> [patch] setando privacidade -> {want}")
        # espera o controle de privacidade EXISTIR (timing: aparece depois do upload)
        for _ in range(30):  # ate 60s
            exists = page.evaluate("""() => !!document.querySelector("div[data-e2e='video_visibility_container'] button[role='combobox']")""")
            if exists:
                break
            _t.sleep(2)
        for attempt in range(6):
            _kill_overlays(page)
            # abre o dropdown via DOM click (clique normal/force e interceptado)
            page.evaluate("""() => { const b=document.querySelector("div[data-e2e='video_visibility_container'] button[role='combobox']"); if(b) b.click(); }""")
            _t.sleep(1.3)
            # escolhe a opcao via DOM click
            clicked = page.evaluate("""(want) => {
              const o=[...document.querySelectorAll("div[role='option']")]
                .find(e=>(e.innerText||'').trim().toLowerCase().startsWith(want.toLowerCase()));
              if(o){ o.click(); return true; } return false;
            }""", want)
            _t.sleep(1.0)
            got = _vis_label(page)
            print(f">> [patch] privacidade atual: {got!r} (opt_click={clicked}, tentativa {attempt+1})")
            if got and want.lower() in got.lower():
                return
        print(">> [patch] NAO consegui confirmar a privacidade")

    # --- PATCH postar: TRAVA de seguranca + clique via DOM ---
    def _post_video_fixed(page):
        _kill_overlays(page)
        got = _vis_label(page)
        print(f">> [patch] checagem final de privacidade antes de postar: {got!r} (exigido: {REQUIRED_LABEL!r})")
        if REQUIRED_LABEL.lower() not in (got or "").lower():
            raise RuntimeError(f"ABORT DE SEGURANCA: privacidade '{got}' != exigido '{REQUIRED_LABEL}'. NAO postei.")
        import pathlib as _pl, re as _re
        _here = _pl.Path(__file__).parent
        # 1) ESPERA o upload terminar 100% (varre todos os frames, tolera nbsp)
        def _uploading():
            for fr in page.frames:
                try:
                    t = fr.evaluate("() => (document.body ? document.body.innerText : '')") or ""
                except Exception:
                    continue
                t = t.replace(" ", " ")
                if _re.search(r"(seconds|minutes)\s+left|uploading", t, _re.I):
                    return True
                m = _re.search(r"\b(\d{1,3})(?:\.\d+)?\s*%", t)
                if m and int(m.group(1)) < 100:
                    return True
            return False
        # sinal confiavel de PRONTO: botao Post habilitado + label de resolucao presente
        def _ready():
            return page.evaluate("""() => {
              const b=document.querySelector("button[data-e2e='post_video_button']");
              const res=document.querySelector("div[class*='resolution-label']");
              return !!b && b.getAttribute('data-disabled')==='false' && !!res;
            }""")
        for _ in range(90):  # ate 3 min
            if _ready():
                break
            _t.sleep(2)
        _t.sleep(2)
        print(">> [patch] video pronto, submetendo")
        # fecha TODOS os popups (loop) e da o clique REAL com scroll
        def _on_form():
            return page.evaluate("() => !!document.querySelector(\"button[data-e2e='post_video_button']\")")
        # localizador do botao Post com fallbacks (se o data-e2e mudar, tenta por texto)
        def _post_btn():
            for sel in ["xpath=//button[@data-e2e='post_video_button']",
                        "xpath=//button[.//div[normalize-space()='Post'] or normalize-space()='Post']",
                        "xpath=//div[contains(@class,'button')]//button[contains(.,'Post')]"]:
                loc = page.locator(sel).first
                try:
                    if loc.count() > 0:
                        return loc
                except Exception:
                    pass
            return page.locator("xpath=//button[@data-e2e='post_video_button']").first
        posted = False
        for i in range(8):
            for _ in range(3):
                _kill_overlays(page); _t.sleep(0.4)
            btn = _post_btn()
            # tenta 3 metodos de clique na ordem que funciona melhor
            try:
                btn.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass
            _t.sleep(0.3)
            done = False
            # 1) coordenada (mouse real) - o mais confiavel hoje
            try:
                box = btn.bounding_box()
                if box:
                    page.mouse.click(box["x"]+box["width"]/2, box["y"]+box["height"]/2)
                    print(f">> [patch] clique coordenada (t{i+1})"); done = True
            except Exception as e:
                print(f">> [patch] coord falhou: {str(e)[:40]}")
            # 2) DOM click
            if not done:
                try:
                    page.evaluate("""() => { const b=document.querySelector("button[data-e2e='post_video_button']")||[...document.querySelectorAll('button')].find(x=>/^post$/i.test((x.innerText||'').trim())); if(b){b.click();return true;} return false; }""")
                    print(f">> [patch] clique DOM (t{i+1})"); done = True
                except Exception:
                    pass
            # 3) clique real do Playwright
            if not done:
                try:
                    btn.click(timeout=5000); print(f">> [patch] clique real (t{i+1})"); done = True
                except Exception as e:
                    print(f">> [patch] real falhou: {str(e)[:40]}")
            if not done:
                _t.sleep(2); continue
            for _ in range(12):
                _t.sleep(1)
                if not _on_form():
                    posted = True; break
                page.evaluate("""() => { const g=[...document.querySelectorAll('[role=dialog] button, .TUXModal button')].filter(b=>b.offsetParent).find(b=>/^(post|post now|publish|confirm)$/i.test((b.innerText||'').trim())); if(g) g.click(); }""")
            if posted:
                print(f">> [patch] POST submetido (tentativa {i+1})")
                break
        try: page.screenshot(path=str(_here/"_postdone.png"))
        except Exception: pass
        if not posted:
            print(">> [patch] AVISO: nao confirmei saida do formulario")

    def _set_interactivity_fixed(page, *a, **k):
        # primeiro setter chamado: fecha o modal de content-check cedo
        _t.sleep(2)
        _kill_overlays(page)
        _t.sleep(0.5)
        _kill_overlays(page)

    up._set_interactivity = _set_interactivity_fixed
    up._set_description = _set_description_fixed
    up._set_visibility = _set_visibility_fixed
    up._post_video = _post_video_fixed
    # --- fim dos patches ---

    sid = sessionid or load_sessionid()
    # v1.2.0 monta o cookie do sessionid SEM dominio -> Playwright recusa.
    # Passamos o cookie completo via cookies_list (dominio/path/flags corretos).
    cookies_list = [{
        "name": "sessionid",
        "value": sid,
        "domain": ".tiktok.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "None",
    }]
    print(f">> upload: {video} | vis={visibility} | headless={headless} | len(sid)={len(sid)}")
    failed = upload_video(
        filename=video,
        description=desc,
        cookies_list=cookies_list,
        visibility=visibility,       # "only_you" = privado (so voce ve)
        browser="chromium",          # usa o chromium do Playwright ja instalado
        headless=headless,
    )
    if failed:
        print(f"!! FALHOU: {failed}")
        return False
    print("OK: upload concluido (sem falhas).")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("uso: run_upload.py <video> <legenda> [only_you|everyone] [headless|headed]")
    _video = sys.argv[1]; _desc = sys.argv[2]
    _vis = sys.argv[3] if len(sys.argv) > 3 else "only_you"
    _hl = (sys.argv[4] if len(sys.argv) > 4 else "headless") == "headless"
    ok = publish(_video, _desc, _vis, _hl)
    sys.exit(0 if ok else 1)
