# tiktok-publisher

Serviço HTTP que publica na @manualdorecemnascido no TikTok pela **rota cookie** (sem app/API
oficial), para a esteira do Motor de Conteúdo. Roda um Chromium headless (Playwright) que dirige a
página de upload do TikTok Studio.

## Como funciona
- `server.py` — HTTP: `GET /health`, `POST /publicar` (header `x-secret`).
- `publicar_tiktok.py` — orquestra: posta → **verifica no Studio** (fonte da verdade) → se a
  privacidade sair errada, **apaga e falha** (nunca deixa post errado no ar). Devolve JSON.
- `run_upload.py` — o upload em si (patches sobre `tiktok-uploader` 1.2.0 p/ a UI atual do TikTok):
  cookie com domínio, fecha o modal "content checks", seta legenda/privacidade via DOM, e clica
  "Postar" por **coordenada** (o único método que submete) após o vídeo processar.
- `delete_last.py` — apaga um post pelo caption (usado na verificação/limpeza).

## Env (EasyPanel)
- `TT_SESSIONID_MRN` — cookie `sessionid` do TikTok da @manualdorecemnascido (expira; renovar).
- `PUBLISH_SECRET` — segredo do header `x-secret`.
- `TT_ALERT_WEBHOOK` — (opcional) webhook n8n que manda alerta no WhatsApp quando quebra.

## Chamada
```
POST http://tiktok-publisher:8000/publicar
Header: x-secret: <PUBLISH_SECRET>
Body: {"video_url":"https://.../video.mp4","caption":"...","visibility":"everyone"}
```
Resposta: `{"ok":true,"verified":true,"privacy":"Everyone",...}`.

## Manutenção
Por ser automação de navegador, o TikTok pode mudar a UI e quebrar um seletor. O serviço se
**auto-verifica** e **alerta** em vez de falhar em silêncio. Cookie vencido = renovar
`TT_SESSIONID_MRN` (DevTools → Application → Cookies → sessionid).
