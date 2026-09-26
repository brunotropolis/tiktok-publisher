"""
Entrypoint de PRODUCAO do publicador TikTok (rota cookie).
Posta -> VERIFICA no Studio (fonte da verdade) -> se privacidade errada, APAGA e falha.
Devolve JSON na ultima linha e exit code (0 ok / 1 falha). Alerta no WhatsApp se TT_ALERT_WEBHOOK.

Uso:
  python publicar_tiktok.py --video <path|url> --caption "..." [--visibility only_you|everyone] [--no-verify] [--headed]
Sessionid: env TT_SESSIONID_MRN ou arquivo .session_mrn.
"""
import sys, os, json, time, argparse, pathlib, tempfile, urllib.request, subprocess
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
VIS_LABEL = {"everyone": "Everyone", "friends": "Friends", "only_you": "Only me"}

def load_sid():
    return (os.environ.get("TT_SESSIONID_MRN") or (HERE/".session_mrn").read_text(encoding="utf-8")).strip()

def alert(msg):
    """Alerta best-effort: POST no webhook em TT_ALERT_WEBHOOK (n8n) se existir."""
    url = os.environ.get("TT_ALERT_WEBHOOK")
    if not url:
        return
    try:
        data = json.dumps({"texto": f"[TikTok esteira] {msg}"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass

def _studio(sid):
    """Abre o Studio e devolve (playwright, browser, page) ja logado (desktop UA)."""
    p = sync_playwright().start()
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=UA, viewport={"width":1440,"height":900}, locale="en-US")
    ctx.add_cookies([{"name":"sessionid","value":sid,"domain":".tiktok.com","path":"/","httpOnly":True,"secure":True,"sameSite":"None"}])
    page = ctx.new_page()
    page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded")
    time.sleep(7)
    return p, b, page

def find_post(page, caption):
    """Acha a linha do post pelo caption. Retorna dict {found, privacy} ou {found:False}."""
    return page.evaluate("""(cap) => {
      const leaf = [...document.querySelectorAll('*')].find(e =>
        e.children.length===0 && e.offsetParent && (e.textContent||'').trim() === cap);
      if (!leaf) return {found:false};
      // sobe ate a linha (que contem 'Everyone'/'Only me'/'Friends')
      let row = leaf;
      for (let i=0;i<12 && row;i++){ row = row.parentElement;
        if (row && /Only me|Everyone|Friends/.test(row.innerText)) break; }
      const txt = row ? row.innerText : '';
      let priv = null;
      for (const p of ['Only me','Friends','Everyone']) if (txt.includes(p)) { priv = p; break; }
      return {found:true, privacy:priv};
    }""", caption)

def delete_post(page, caption):
    """Apaga o post pelo caption (menu ... -> Delete -> confirm)."""
    box = page.evaluate("""(cap) => {
      const leaf=[...document.querySelectorAll('*')].find(e=>e.children.length===0 && e.offsetParent && (e.textContent||'').trim()===cap && e.getBoundingClientRect().y>40);
      if(!leaf) return null; const cr=leaf.getBoundingClientRect(); const cy=cr.y+cr.height/2;
      const btns=[...document.querySelectorAll('button')].filter(bt=>{const r=bt.getBoundingClientRect();const y=r.y+r.height/2;return Math.abs(y-cy)<28 && r.x>1050 && r.width<60;});
      if(!btns.length) return null; btns.sort((a,b)=>a.getBoundingClientRect().x-b.getBoundingClientRect().x);
      const r=btns[btns.length-1].getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2};
    }""", caption)
    if not box: return False
    page.mouse.click(box["x"], box["y"]); time.sleep(1.2)
    d = page.evaluate("""() => { const el=[...document.querySelectorAll('*')].find(e=>e.children.length===0 && e.offsetParent && /^(delete|excluir)$/i.test((e.textContent||'').trim())); if(!el)return null; const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
    if not d: return False
    page.mouse.click(d["x"], d["y"]); time.sleep(1.2)
    page.evaluate("""() => { const b=[...document.querySelectorAll('button')].filter(x=>x.offsetParent).find(x=>/^(delete|excluir|confirm)$/i.test((x.innerText||'').trim())); if(b) b.click(); }""")
    time.sleep(3)
    return not page.evaluate("(c)=>document.body.innerText.includes(c)", caption)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="caminho local ou URL http(s)")
    ap.add_argument("--caption", required=True)
    ap.add_argument("--visibility", default="only_you", choices=["only_you","everyone","friends"])
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()

    result = {"ok": False, "reason": None, "privacy": None, "verified": False}
    tmp = None
    try:
        sid = load_sid()
        video = a.video
        if video.startswith("http"):
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir=str(HERE))
            urllib.request.urlretrieve(video, tmp.name); video = tmp.name
            print(f">> baixado: {video}")

        # UPLOAD em subprocesso (isola o Playwright do upload da verificacao)
        env = dict(os.environ, TT_SESSIONID_MRN=sid, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HERE/"run_upload.py"), video, a.caption, a.visibility,
             ("headed" if a.headed else "headless")],
            env=env, cwd=str(HERE), capture_output=True, text=True, timeout=900)
        sys.stderr.write(proc.stdout[-2000:] if proc.stdout else "")
        ok = (proc.returncode == 0)
        if not ok:
            result["reason"] = "upload_video reportou falha"
            alert(f"FALHA ao postar (upload nao concluiu): {a.caption[:40]}")
            print(json.dumps(result)); sys.exit(1)

        if a.no_verify:
            result.update(ok=True, reason="postado (sem verificacao)")
            print(json.dumps(result)); sys.exit(0)

        # VERIFICACAO no Studio (fonte da verdade)
        want = VIS_LABEL.get(a.visibility, "Everyone")
        p=b=None
        try:
            p, b, page = _studio(sid)
            info = find_post(page, a.caption)
            if not info.get("found"):
                result["reason"] = "post NAO apareceu no Studio (provavel quebra de UI)"
                alert(f"FALHA: post nao apareceu no Studio: {a.caption[:40]}")
            elif info.get("privacy") != want:
                # privacidade errada -> APAGA (seguranca) e falha
                deleted = delete_post(page, a.caption)
                result["privacy"] = info.get("privacy")
                result["reason"] = f"privacidade '{info.get('privacy')}' != '{want}' -> apagado={deleted}"
                alert(f"FALHA: privacidade errada ({info.get('privacy')} != {want}), apagado={deleted}: {a.caption[:40]}")
            else:
                result.update(ok=True, verified=True, privacy=info.get("privacy"), reason="ok, verificado no Studio")
        finally:
            try:
                if b: b.close()
                if p: p.stop()
            except Exception:
                pass
    except Exception as e:
        result["reason"] = f"excecao: {e}"
        alert(f"ERRO na esteira TikTok: {str(e)[:80]}")
    finally:
        if tmp:
            try: os.unlink(tmp.name)
            except Exception: pass

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)

if __name__ == "__main__":
    main()
