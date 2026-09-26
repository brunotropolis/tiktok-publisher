"""
Abre o TikTok Studio (desktop, via cookie) e DELETA o post cujo caption casa TARGET.
Uso: python delete_last.py "<trecho do caption>" [--go]
Sem --go: so mostra o que faria (dry). Com --go: executa o delete.
Screenshots: _shot1.png (lista), _shot2.png (menu), _shot3.png (confirm), _shot4.png (fim).
"""
import sys, time, pathlib
from playwright.sync_api import sync_playwright

args = sys.argv[1:]
GO = "--go" in args
args = [a for a in args if a != "--go"]
TARGET = args[0] if args else "teste interno motor"
HERE = pathlib.Path(__file__).parent
SID = (HERE / ".session_mrn").read_text(encoding="utf-8").strip()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

def shot(page, n): page.screenshot(path=str(HERE / f"_shot{n}.png"))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=UA, viewport={"width":1440,"height":900}, locale="en-US")
    ctx.add_cookies([{"name":"sessionid","value":SID,"domain":".tiktok.com","path":"/","httpOnly":True,"secure":True,"sameSite":"None"}])
    page = ctx.new_page()
    page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded")
    time.sleep(6)
    shot(page, 1)

    # Acha a linha do TARGET e o bbox do botao "..." (ultimo botao de acao da linha)
    box = page.evaluate("""(target) => {
      const cap = [...document.querySelectorAll('*')].find(e => {
        if (e.children.length !== 0) return false;
        if (!e.textContent || !e.textContent.includes(target)) return false;
        if (!e.offsetParent) return false;
        const r = e.getBoundingClientRect();
        return r.height > 0 && r.y > 40;
      });
      if (!cap) return {err: 'caption visivel nao encontrado'};
      const cr = cap.getBoundingClientRect();
      const capY = cr.y + cr.height/2;
      // botoes de acao na MESMA linha (mesmo Y, lado direito)
      const btns = [...document.querySelectorAll('button')].filter(bt => {
        const r = bt.getBoundingClientRect();
        const y = r.y + r.height/2;
        return Math.abs(y - capY) < 28 && r.x > 1050 && r.width < 60 && r.height < 60;
      });
      if (!btns.length) return {err:'nenhum botao de acao na linha', capY};
      btns.sort((a,bb)=> a.getBoundingClientRect().x - bb.getBoundingClientRect().x);
      const more = btns[btns.length-1]; // mais a direita = "..."
      const r = more.getBoundingClientRect();
      return {x: r.x + r.width/2, y: r.y + r.height/2, nBtns: btns.length, capY};
    }""", TARGET)
    print("more-button box:", box)
    if box.get("err"):
        print("ABORT:", box["err"]); b.close(); sys.exit(1)

    page.mouse.click(box["x"], box["y"])
    time.sleep(1.5)
    shot(page, 2)
    # dump itens do menu aberto
    menu = page.evaluate("""() => {
      const items = [...document.querySelectorAll('[role="menuitem"], li, [class*="menu"] *')]
        .filter(e => e.children.length===0 && e.textContent && e.textContent.trim().length>0 && e.offsetParent)
        .map(e => e.textContent.trim());
      return [...new Set(items)].slice(0,30);
    }""")
    print("menu items:", menu)

    # acha o item Delete/Excluir e seu bbox
    del_box = page.evaluate("""() => {
      const el = [...document.querySelectorAll('*')].find(e =>
        e.children.length===0 && e.offsetParent && /^(delete|excluir)$/i.test((e.textContent||'').trim()));
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {x:r.x+r.width/2, y:r.y+r.height/2, t:el.textContent.trim()};
    }""")
    print("delete item:", del_box)

    if not GO:
        print(">> DRY: nao cliquei em Delete (rode com --go).")
        b.close(); sys.exit(0)

    if not del_box:
        print("ABORT: item Delete nao encontrado"); b.close(); sys.exit(1)
    page.mouse.click(del_box["x"], del_box["y"])
    time.sleep(1.5)
    shot(page, 3)
    # dialogo de confirmacao -> botao Delete/Excluir/Confirm
    conf = page.evaluate("""() => {
      const btns = [...document.querySelectorAll('button')].filter(b=>b.offsetParent);
      const t = b => (b.innerText||'').trim();
      let el = btns.find(b => /^(delete|excluir|confirm|remove)$/i.test(t(b)));
      if (!el) el = btns.reverse().find(b => /(delete|excluir|confirm)/i.test(t(b)));
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {x:r.x+r.width/2, y:r.y+r.height/2, t: t(el)};
    }""")
    print("confirm button:", conf)
    if conf:
        page.mouse.click(conf["x"], conf["y"])
        time.sleep(3)
    shot(page, 4)
    # verifica se sumiu
    still = page.evaluate("(t)=>document.body.innerText.includes(t)", TARGET)
    print("ainda presente na lista?", still)
    b.close()
