"""
Servico HTTP do publicador TikTok (rota cookie) para a esteira do Motor de Conteudo.
Endpoints:
  GET  /health                      -> {"ok":true}
  POST /publicar {video_url, caption, visibility?, schedule?}  (header x-secret)
       -> roda publicar_tiktok.py e devolve o JSON de resultado.
Env:
  TT_SESSIONID_MRN  (cookie de sessao @manualdorecemnascido) - obrigatorio
  PUBLISH_SECRET    (segredo do header x-secret) - obrigatorio
  TT_ALERT_WEBHOOK  (opcional; webhook n8n de alerta WhatsApp)
"""
import os, json, subprocess, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = os.environ.get("PUBLISH_SECRET", "")

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

        cmd = [sys.executable, os.path.join(HERE, "publicar_tiktok.py"),
               "--video", video, "--caption", caption, "--visibility", visibility]
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
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
