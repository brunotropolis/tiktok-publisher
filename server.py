"""
Servico HTTP do publicador TikTok (rota cookie) para a esteira do Motor de Conteudo.
Endpoints:
  GET  /health                      -> {"ok":true}
  GET  /check  (header x-secret)    -> confere se o cookie de sessao ainda loga na conta
       -> {"ok":true,"username":...} ou {"ok":false,"reason":...} (usado pelo alerta diario)
  GET  /check?conta=brunotropolis   -> idem para outra conta (padrao = mrn)
  POST /publicar {video_url, caption, visibility?, schedule?, conta?}  (header x-secret)
       conta = "mrn" (padrao, @manualdorecemnascido) ou outra com env TT_SESSIONID_<CONTA> (ex. brunotropolis)
       -> roda publicar_tiktok.py e devolve o JSON de resultado.
Env:
  TT_SESSIONID_MRN  (cookie de sessao @manualdorecemnascido) - obrigatorio
  TT_SESSIONID_<CONTA> (multi-conta, 26/Out; ex. TT_SESSIONID_BRUNOTROPOLIS) - opcional
  PUBLISH_SECRET    (segredo do header x-secret) - obrigatorio
  TT_ALERT_WEBHOOK  (opcional; webhook n8n de alerta WhatsApp)
"""
import os, json, re, subprocess, sys, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = os.environ.get("PUBLISH_SECRET", "")

def sessao(conta):
    """sessionid da conta pedida. Sem conta (ou "mrn") = Day, como sempre. Conta desconhecida = None (nunca cai na Day)."""
    conta = (conta or "mrn").strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{2,40}", conta):
        return None
    return os.environ.get("TT_SESSIONID_" + conta.upper()) or None

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silencia log padrao
        pass

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            return self._send(200, {"ok": True, "service": "tiktok-publisher"})
        u = urllib.parse.urlparse(self.path)
        if u.path.rstrip("/") == "/check":
            if not SECRET or self.headers.get("x-secret") != SECRET:
                return self._send(401, {"ok": False, "reason": "unauthorized"})
            conta = (urllib.parse.parse_qs(u.query).get("conta") or ["mrn"])[0]
            return self._send(200, checar_sessao(conta))
        return self._send(404, {"ok": False, "reason": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/publicar":
            return self._send(404, {"ok": False, "reason": "not found"})
        if not SECRET or self.headers.get("x-secret") != SECRET:
            return self._send(401, {"ok": False, "reason": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, {"ok": False, "reason": f"json invalido: {e}"})

        video = data.get("video_url") or data.get("video")
        caption = data.get("caption", "")
        visibility = data.get("visibility", "everyone")
        if not video:
            return self._send(400, {"ok": False, "reason": "falta video_url"})
        sid = sessao(data.get("conta"))
        if not sid:
            return self._send(400, {"ok": False, "reason": "conta sem sessao: " + str(data.get("conta"))[:40]})

        cmd = [sys.executable, os.path.join(HERE, "publicar_tiktok.py"),
               "--video", video, "--caption", caption, "--visibility", visibility]
        # o publicar_tiktok.py le TT_SESSIONID_MRN: passa a sessao da conta pedida por ali
        env = dict(os.environ, TT_SESSIONID_MRN=sid, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        try:
            proc = subprocess.run(cmd, env=env, cwd=HERE, capture_output=True,
                                  text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            return self._send(504, {"ok": False, "reason": "timeout (1200s)"})
        # a ultima linha do stdout e o JSON de resultado
        result = {"ok": False, "reason": "sem saida"}
        for line in reversed((proc.stdout or "").strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line); break
                except Exception:
                    continue
        result["exit"] = proc.returncode
        return self._send(200 if result.get("ok") else 502, result)

def checar_sessao(conta="mrn"):
    """Pergunta ao TikTok quem esta logado com o cookie atual (sem abrir navegador)."""
    sid = sessao(conta)
    if not sid:
        return {"ok": False, "reason": "sem sessao para a conta " + str(conta)[:40]}
    req = urllib.request.Request(
        "https://www.tiktok.com/passport/web/account/info/?aid=1459",
        headers={"Cookie": "sessionid=" + sid,
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=20).read() or b"{}")
    except Exception as e:
        return {"ok": False, "reason": f"falha ao consultar o TikTok: {e}"[:200], "rede": True}
    dados = d.get("data") or {}
    if d.get("message") == "success" and dados.get("username"):
        return {"ok": True, "username": dados.get("username")}
    return {"ok": False, "reason": "sessao expirada ou invalida", "codigo": dados.get("error_code")}

def main():
    if not os.environ.get("TT_SESSIONID_MRN"):
        print("AVISO: TT_SESSIONID_MRN nao definido", file=sys.stderr)
    if not SECRET:
        print("AVISO: PUBLISH_SECRET nao definido (endpoint ficara 401)", file=sys.stderr)
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    print(f"tiktok-publisher ouvindo em :{port}")
    srv.serve_forever()

if __name__ == "__main__":
    main()
