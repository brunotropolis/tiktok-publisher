"""
Entrypoint de PRODUCAO do publicador TikTok (rota cookie).
Posta -> VERIFICA no Studio (fonte da verdade) -> se privacidade errada, APAGA e falha.
Devolve JSON na ultima linha e exit code (0 ok / 1 falha). Alerta no WhatsApp se TT_ALERT_WEBHOOK.

Uso:
  python publicar_tiktok.py --video <path|url> --caption "..." [--visibility only_you|everyone] [--no-verify] [--headed]
  python publicar_tiktok.py --fotos '["url1","url2",...]' --caption "..." [--som "termo"|nenhum]   (carrossel de fotos, 25/Nov)
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

def find_post(page, caption, desde=0):
    """Acha o post NOVO na lista do Studio. Fonte: o id do vídeo (/video/<id>) carrega a hora da postagem
    (id >> 32 = segundos unix) -> procura vídeo postado a partir de `desde` (início do upload - 2 min).
    NÃO compara pela legenda: o Studio mostra a legenda cortada/com hashtags separadas e as legendas B
    começam todas iguais (bug 09 e 12/Out: postou, mas a checagem dizia que não).
    Retorna {found, privacy, id} ou {found:False}."""
    return page.evaluate("""(desde) => {
      const links = [...document.querySelectorAll('a[href*="/video/"]')];
      let melhor = null;
      for (const a of links) {
        const id = (a.href.split('/video/')[1] || '').split('?')[0].split('/')[0]; if (!/^[0-9]+$/.test(id)) continue; const m = [null, id];
        const ts = Number(BigInt(m[1]) >> 32n);
        if (ts >= desde && (!melhor || ts > melhor.ts)) melhor = {a, ts, id: m[1]};
      }
      if (!melhor) return {found:false};
      let row = melhor.a;
      for (let i=0;i<14 && row;i++){ row = row.parentElement;
        if (row && /Only me|Everyone|Friends|Somente eu|Todos|Amigos/.test(row.innerText)) break; }
      const txt = row ? row.innerText : '';
      const mapa = {'Only me':'Only me','Somente eu':'Only me','Friends':'Friends','Amigos':'Friends','Everyone':'Everyone','Todos':'Everyone'};
      let priv = null;
      for (const k of Object.keys(mapa)) if (txt.includes(k)) { priv = mapa[k]; break; }
      return {found:true, privacy:priv, id:melhor.id, ts:melhor.ts};
    }""", desde)

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
    ap.add_argument("--video", help="caminho local ou URL http(s)")
    ap.add_argument("--fotos", help='JSON: lista de caminhos/URLs das fotos do carrossel (ate 35)')
    ap.add_argument("--som", default="", help="termo de busca do som (vazio = 1a sugestao For You; nenhum = sem som)")
    ap.add_argument("--caption", required=True)
    ap.add_argument("--visibility", default="only_you", choices=["only_you","everyone","friends"])
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    if not a.video and not a.fotos:
        ap.error("precisa de --video ou --fotos")

    result = {"ok": False, "reason": None, "privacy": None, "verified": False}
    tmp = None
    tmpdir = None
    try:
        sid = load_sid()
        if a.fotos:
            tmpdir = tempfile.mkdtemp(prefix="fotos_", dir=str(HERE))
            locais = []
            for i, f in enumerate(json.loads(a.fotos)[:35]):
                if str(f).startswith("http"):
                    ext = ".png" if ".png" in f.lower() else (".webp" if ".webp" in f.lower() else ".jpg")
                    dst = os.path.join(tmpdir, f"{i+1:02d}{ext}")
                    urllib.request.urlretrieve(f, dst); locais.append(dst)
                else:
                    locais.append(f)
            lista = os.path.join(tmpdir, "lista.json")
            json.dump(locais, open(lista, "w", encoding="utf-8"))
            print(f">> {len(locais)} fotos baixadas")
        else:
            video = a.video
            if video.startswith("http"):
                tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir=str(HERE))
                urllib.request.urlretrieve(video, tmp.name); video = tmp.name
                print(f">> baixado: {video}")

        inicio = int(time.time()) - 120  # vídeo postado a partir daqui = o nosso
        # UPLOAD em subprocesso (isola o Playwright do upload da verificacao)
        env = dict(os.environ, TT_SESSIONID_MRN=sid, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", TT_SOM=a.som or "")
        if a.fotos:
            cmd = [sys.executable, str(HERE/"run_photos.py"), lista, a.caption, a.visibility, ("headed" if a.headed else "headless")]
        else:
            cmd = [sys.executable, str(HERE/"run_upload.py"), video, a.caption, a.visibility, ("headed" if a.headed else "headless")]
        proc = subprocess.run(cmd, env=env, cwd=str(HERE), capture_output=True, text=True, timeout=900)
        for ln in (proc.stdout or "").splitlines():
            if ln.startswith(">> som: "):
                result["som"] = ln[8:].strip()[:120]
        sys.stderr.write(proc.stdout[-2000:] if proc.stdout else "")
        ok = (proc.returncode == 0)
        if not ok:
            result["reason"] = "upload reportou falha: " + ((proc.stdout or "") + (proc.stderr or "")).strip()[-300:]
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
            info = find_post(page, a.caption, inicio)
            if not info.get("found"):  # lista pode demorar a atualizar
                time.sleep(20); page.reload(wait_until="domcontentloaded"); time.sleep(8)
                info = find_post(page, a.caption, inicio)
            if not info.get("found"):
                result["reason"] = "post NAO apareceu no Studio (provavel quebra de UI)"
                alert(f"FALHA: post nao apareceu no Studio: {a.caption[:40]}")
            # Logo após postar o TikTok mostra "Only me" enquanto processa e depois vira o certo (bug 15-19/Out:
            # marcava falha e tentava APAGAR post que ficou público). Reconfere a cada 30s por até ~5 min.
            tentativas = 0
            while info.get("found") and info.get("privacy") != want and tentativas < 10:
                tentativas += 1
                time.sleep(30); page.reload(wait_until="domcontentloaded"); time.sleep(8)
                info = find_post(page, a.caption, inicio) or info
            NIVEL = {"Only me": 0, "Friends": 1, "Everyone": 2}
            if not info.get("found"):
                pass
            elif info.get("privacy") != want:
                result["privacy"] = info.get("privacy")
                if NIVEL.get(info.get("privacy"), 0) > NIVEL.get(want, 2):
                    # MAIS aberto que o pedido (ex.: queria só eu e saiu público) -> apaga por segurança
                    deleted = delete_post(page, a.caption)
                    result["reason"] = f"privacidade '{info.get('privacy')}' mais aberta que '{want}' -> apagado={deleted}"
                    alert(f"FALHA: saiu mais aberto que o pedido ({info.get('privacy')} != {want}), apagado={deleted}: {a.caption[:40]}")
                else:
                    # MAIS fechado que o pedido: nunca apaga (pode ser só processamento/revisão do TikTok)
                    result["id"] = info.get("id")
                    result["reason"] = f"postado, mas o TikTok ainda mostra '{info.get('privacy')}' (esperado '{want}') depois de 5 min: conferir no app"
                    alert(f"ATENÇÃO: post ainda '{info.get('privacy')}' depois de 5 min (deveria ser {want}): {a.caption[:40]}")
            else:
                result.update(ok=True, verified=True, privacy=info.get("privacy"), id=info.get("id"), reason="ok, verificado no Studio")
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
        try:
            import shutil
            if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)

if __name__ == "__main__":
    main()
