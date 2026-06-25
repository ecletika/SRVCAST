import hashlib
import hmac
import html
import os
import secrets
import time
from urllib.parse import parse_qs, quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse


SESSION_COOKIE = "srvcast_admin_session"
SESSION_SECONDS = int(os.getenv("ADMIN_SESSION_SECONDS", "28800"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")


def register_admin_pro(app, SessionLocal, Room, PairSession, PairToken, select, ADMIN_TOKEN, GATEWAY_TOKEN, PUBLIC_BASE_URL):
    secret_key = os.getenv("SECRET_KEY", ADMIN_TOKEN + GATEWAY_TOKEN)

    def e(value):
        return html.escape(str(value or ""))

    def css():
        return """
        <style>
        body{margin:0;background:#0f172a;color:#e5e7eb;font-family:Arial,Helvetica,sans-serif}
        .wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:12px;align-items:center}
        .card{background:#111827;border:1px solid #273449;border-radius:14px;padding:16px;margin:14px 0}
        .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
        input,textarea,select{width:100%;padding:10px;border-radius:9px;border:1px solid #273449;background:#0b1220;color:#e5e7eb}
        textarea{min-height:130px}label{font-size:12px;color:#94a3b8;display:block;margin:8px 0 4px}
        button,.btn{background:#2563eb;color:white;border:0;border-radius:9px;padding:9px 12px;cursor:pointer;text-decoration:none;display:inline-block;margin:3px}
        .danger{background:#ef4444}.warn{background:#f59e0b;color:#111827}.secondary{background:#334155}.ok{background:#22c55e;color:#052e16}
        table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #273449;padding:8px;text-align:left;vertical-align:top}
        th{color:#94a3b8;font-weight:normal}.msg{background:#0b1220;border-left:4px solid #22c55e;padding:10px;border-radius:8px;white-space:pre-wrap}
        .muted{color:#94a3b8}.mono{font-family:Consolas,monospace}.actions{white-space:nowrap}.nav a{margin-right:8px}
        .stat{font-size:30px;font-weight:bold}.badgetxt{padding:4px 8px;border-radius:999px;background:#334155}.active{background:#064e3b;color:#bbf7d0}.off{background:#7f1d1d;color:#fecaca}
        @media(max-width:900px){.grid,.grid2{grid-template-columns:1fr}.actions{white-space:normal}.top{display:block}}
        </style>
        """

    def page(title, body, user="admin", msg=""):
        flash = f'<div class="msg">{e(msg)}</div>' if msg else ""
        nav = """
        <div class="nav">
          <a class="btn secondary" href="/admin">Dashboard</a>
          <a class="btn secondary" href="/admin/rooms">Quartos</a>
          <a class="btn secondary" href="/admin/pairings">Pareamentos</a>
          <a class="btn secondary" href="/admin/diagnostic">Diagnóstico</a>
          <a class="btn danger" href="/admin/logout">Sair</a>
        </div>
        """
        return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>{css()}</head><body><div class="wrap"><div class="top"><div><h1>{e(title)}</h1><p class="muted">SRVCAST Admin Pro · logado como <b>{e(user)}</b> · base pública <b>{e(PUBLIC_BASE_URL)}</b></p></div>{nav}</div>{flash}{body}</div></body></html>""")

    def make_sig(payload):
        return hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def make_cookie(username):
        exp = int(time.time()) + SESSION_SECONDS
        payload = f"{username}|{exp}"
        return payload + "|" + make_sig(payload)

    def check_cookie(request):
        raw = request.cookies.get(SESSION_COOKIE, "")
        try:
            username, exp, sig = raw.split("|", 2)
            payload = f"{username}|{exp}"
            if not hmac.compare_digest(sig, make_sig(payload)):
                return None
            if int(exp) < int(time.time()):
                return None
            return username
        except Exception:
            return None

    async def form_data(request):
        body = (await request.body()).decode("utf-8", errors="ignore")
        parsed = parse_qs(body, keep_blank_values=True)
        return {k: v[0] if v else "" for k, v in parsed.items()}

    def verify_password(password):
        if ADMIN_PASSWORD_HASH:
            # formato suportado: sha256$salt$hashhex
            try:
                alg, salt, digest = ADMIN_PASSWORD_HASH.split("$", 2)
                if alg == "sha256":
                    got = hashlib.sha256((salt + password).encode()).hexdigest()
                    return hmac.compare_digest(got, digest)
            except Exception:
                return False
        expected = ADMIN_PASSWORD or ADMIN_TOKEN
        return hmac.compare_digest(password, expected)

    def require_login(request):
        user = check_cookie(request)
        if not user:
            raise HTTPException(401, "login necessário")
        return user

    def db():
        return SessionLocal()

    def save_room(s, room_number, cast_name, cast_ip, cast_mac, enabled):
        room_number = room_number.strip()
        cast_name = cast_name.strip()
        cast_ip = cast_ip.strip()
        cast_mac = (cast_mac or "").strip() or None
        room = s.scalar(select(Room).where(Room.room_number == room_number))
        if room:
            room.cast_name = cast_name
            room.cast_ip = cast_ip
            room.cast_mac = cast_mac
            room.enabled = enabled
        else:
            room = Room(room_number=room_number, cast_name=cast_name, cast_ip=cast_ip, cast_mac=cast_mac, enabled=enabled)
            s.add(room)
        s.commit()
        return room

    def redirect(path, msg=""):
        if msg:
            sep = "&" if "?" in path else "?"
            path = path + sep + "msg=" + quote(msg)
        return RedirectResponse(path, status_code=303)

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_home(request: Request, msg: str = ""):
        user = check_cookie(request)
        if not user:
            login = f"""
            <div class="wrap"><div class="card" style="max-width:520px;margin:60px auto">
              <h1>SRVCAST Admin Pro</h1>
              <p class="muted">Entre com utilizador e senha. Enquanto não definires ADMIN_PASSWORD, a senha é o ADMIN_TOKEN.</p>
              {('<div class="msg">'+e(msg)+'</div>') if msg else ''}
              <form method="post" action="/admin/login">
                <label>Utilizador</label><input name="username" value="{e(ADMIN_USERNAME)}" autofocus>
                <label>Senha</label><input name="password" type="password">
                <br><br><button type="submit">Entrar</button>
              </form>
            </div></div>
            """
            return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><title>SRVCAST Login</title>{css()}</head><body>{login}</body></html>")
        s = db()
        try:
            rooms = list(s.scalars(select(Room)))
            sessions = list(s.scalars(select(PairSession).where(PairSession.active == True)))
            active_rooms = len([r for r in rooms if r.enabled])
            body = f"""
            <div class="grid">
              <div class="card"><div class="muted">Quartos</div><div class="stat">{len(rooms)}</div></div>
              <div class="card"><div class="muted">Quartos ativos</div><div class="stat">{active_rooms}</div></div>
              <div class="card"><div class="muted">Pareamentos ativos</div><div class="stat">{len(sessions)}</div></div>
              <div class="card"><div class="muted">Sessão admin</div><div class="stat">OK</div></div>
            </div>
            <div class="card"><h2>Próximos passos</h2><p>Use a aba <b>Quartos</b> para cadastrar nomes/IPs dos Chromecasts. Use <b>Pareamentos</b> para ver quem está autorizado e desconectar pelo servidor.</p></div>
            """
            return page("Dashboard", body, user, msg)
        finally:
            s.close()

    @app.post("/admin/login")
    async def admin_login(request: Request):
        data = await form_data(request)
        username = data.get("username", "")
        password = data.get("password", "")
        if username != ADMIN_USERNAME or not verify_password(password):
            return redirect("/admin", "Utilizador ou senha inválidos")
        resp = redirect("/admin", "Login realizado")
        resp.set_cookie(SESSION_COOKIE, make_cookie(username), httponly=True, samesite="lax", max_age=SESSION_SECONDS)
        return resp

    @app.get("/admin/logout")
    async def admin_logout():
        resp = redirect("/admin", "Sessão terminada")
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    @app.get("/admin/rooms", response_class=HTMLResponse)
    async def admin_rooms(request: Request, edit: str = "", msg: str = ""):
        user = require_login(request)
        s = db()
        try:
            rooms = list(s.scalars(select(Room).order_by(Room.room_number)))
            editing = s.scalar(select(Room).where(Room.room_number == edit)) if edit else None
            rows = ""
            for r in rooms:
                rows += f"""<tr><td><b>{e(r.room_number)}</b></td><td>{e(r.cast_name)}</td><td>{e(r.cast_ip)}</td><td>{e(r.cast_mac)}</td><td><span class="badgetxt {'active' if r.enabled else 'off'}">{'Ativo' if r.enabled else 'Desativado'}</span></td><td class="actions"><a class="btn secondary" href="/tv/{quote(r.room_number)}" target="_blank">TV/QR</a><a class="btn warn" href="/admin/rooms?edit={quote(r.room_number)}">Editar</a><form method="post" action="/admin/rooms/checkout" style="display:inline"><input type="hidden" name="room" value="{e(r.room_number)}"><button class="secondary">Checkout</button></form><form method="post" action="/admin/rooms/delete" style="display:inline" onsubmit="return confirm('Excluir quarto {e(r.room_number)}?')"><input type="hidden" name="room" value="{e(r.room_number)}"><button class="danger">Excluir</button></form></td></tr>"""
            if not rows:
                rows = '<tr><td colspan="6">Nenhum quarto cadastrado.</td></tr>'
            val = lambda attr: e(getattr(editing, attr, "") if editing else "")
            sel_on = "selected" if (not editing or editing.enabled) else ""
            sel_off = "selected" if (editing and not editing.enabled) else ""
            body = f"""
            <div class="grid2">
              <div class="card"><h2>{'Editar' if editing else 'Criar'} quarto</h2><form method="post" action="/admin/rooms/save">
                <label>Número/nome do quarto</label><input name="room_number" required value="{val('room_number')}" placeholder="101, 205A, Suite Azul">
                <label>Nome do Cast</label><input name="cast_name" required value="{val('cast_name')}" placeholder="Quarto-101">
                <label>IP do Chromecast</label><input name="cast_ip" required value="{val('cast_ip')}" placeholder="10.10.10.11">
                <label>MAC opcional</label><input name="cast_mac" value="{val('cast_mac')}" placeholder="D8:EB:46:6B:ED:A0">
                <label>Ativo</label><select name="enabled"><option value="1" {sel_on}>Sim</option><option value="0" {sel_off}>Não</option></select><br><br>
                <button>Salvar quarto</button><a class="btn secondary" href="/admin/rooms">Limpar</a>
              </form></div>
              <div class="card"><h2>Importar vários</h2><p class="muted">Uma linha: <span class="mono">quarto;nome_cast;ip_cast;mac_opcional</span></p><form method="post" action="/admin/rooms/import"><textarea name="bulk" placeholder="101;Quarto-101;10.10.10.11;D8:EB:46:6B:ED:A0&#10;205A;Quarto-205A;10.10.10.12"></textarea><br><br><button>Importar/atualizar</button></form></div>
            </div>
            <div class="card"><h2>Quartos cadastrados</h2><table><thead><tr><th>Quarto</th><th>Cast</th><th>IP</th><th>MAC</th><th>Status</th><th>Ações</th></tr></thead><tbody>{rows}</tbody></table></div>
            """
            return page("Quartos / Chromecasts", body, user, msg)
        finally:
            s.close()

    @app.post("/admin/rooms/save")
    async def admin_rooms_save(request: Request):
        require_login(request)
        data = await form_data(request)
        s = db()
        try:
            if not data.get("room_number") or not data.get("cast_name") or not data.get("cast_ip"):
                return redirect("/admin/rooms", "Preencha quarto, nome do Cast e IP")
            save_room(s, data["room_number"], data["cast_name"], data["cast_ip"], data.get("cast_mac", ""), data.get("enabled") in ("1", "true", "on"))
            return redirect("/admin/rooms", "Quarto salvo: " + data["room_number"])
        finally:
            s.close()

    @app.post("/admin/rooms/import")
    async def admin_rooms_import(request: Request):
        require_login(request)
        data = await form_data(request)
        s = db()
        ok, errors = 0, []
        try:
            for line in data.get("bulk", "").splitlines():
                line = line.strip()
                if not line:
                    continue
                p = [x.strip() for x in line.split(";")]
                if len(p) < 3:
                    errors.append("Linha inválida: " + line)
                    continue
                save_room(s, p[0], p[1], p[2], p[3] if len(p) > 3 else "", True)
                ok += 1
            msg = f"Importados/atualizados: {ok}" + (("\nErros:\n" + "\n".join(errors)) if errors else "")
            return redirect("/admin/rooms", msg)
        finally:
            s.close()

    @app.post("/admin/rooms/delete")
    async def admin_rooms_delete(request: Request):
        require_login(request)
        data = await form_data(request)
        s = db()
        try:
            room_number = data.get("room", "")
            r = s.scalar(select(Room).where(Room.room_number == room_number))
            if not r:
                return redirect("/admin/rooms", "Quarto não encontrado")
            s.query(PairSession).filter(PairSession.room_id == r.id).delete()
            s.query(PairToken).filter(PairToken.room_id == r.id).delete()
            s.delete(r)
            s.commit()
            return redirect("/admin/rooms", "Quarto excluído: " + room_number)
        finally:
            s.close()

    @app.post("/admin/rooms/checkout")
    async def admin_rooms_checkout(request: Request):
        require_login(request)
        data = await form_data(request)
        s = db()
        try:
            room_number = data.get("room", "")
            r = s.scalar(select(Room).where(Room.room_number == room_number))
            if not r:
                return redirect("/admin/rooms", "Quarto não encontrado")
            n = s.query(PairSession).filter(PairSession.room_id == r.id, PairSession.active == True).update({"active": False})
            s.commit()
            return redirect("/admin/rooms", f"Checkout feito no quarto {room_number}. Sessões fechadas: {n}")
        finally:
            s.close()

    @app.get("/admin/pairings", response_class=HTMLResponse)
    async def admin_pairings(request: Request, msg: str = ""):
        user = require_login(request)
        s = db()
        try:
            sessions = list(s.scalars(select(PairSession).where(PairSession.active == True).order_by(PairSession.expires_at)))
            rows = ""
            for ps in sessions:
                r = s.get(Room, ps.room_id)
                if not r:
                    continue
                rows += f"""<tr><td>{ps.id}</td><td><b>{e(r.room_number)}</b></td><td>{e(ps.guest_ip)}</td><td>{e(r.cast_name)}</td><td>{e(r.cast_ip)}</td><td>{e(ps.expires_at)}</td><td class="actions"><form method="post" action="/admin/pairings/disconnect" style="display:inline"><input type="hidden" name="session_id" value="{ps.id}"><button class="danger">Desconectar</button></form><form method="post" action="/admin/pairings/disconnect-room" style="display:inline"><input type="hidden" name="room" value="{e(r.room_number)}"><button class="warn">Desconectar quarto</button></form></td></tr>"""
            if not rows:
                rows = '<tr><td colspan="7">Nenhum hóspede pareado agora.</td></tr>'
            body = f"""
            <div class="card"><h2>Pareamentos ativos</h2><p class="muted">Aqui aparece quem está autorizado a fazer Cast e para qual Chromecast.</p><table><thead><tr><th>ID</th><th>Quarto</th><th>IP do hóspede</th><th>Cast autorizado</th><th>IP do Cast</th><th>Expira em</th><th>Ações</th></tr></thead><tbody>{rows}</tbody></table></div>
            <div class="card"><h2>Ações globais</h2><form method="post" action="/admin/pairings/disconnect-all" onsubmit="return confirm('Desconectar todos os hóspedes?')"><button class="danger">Desconectar todos os hóspedes</button></form></div>
            """
            return page("Pareamentos ativos", body, user, msg)
        finally:
            s.close()

    @app.post("/admin/pairings/disconnect")
    async def admin_disconnect(request: Request):
        require_login(request)
        data = await form_data(request)
        s = db()
        try:
            sid = int(data.get("session_id", "0") or 0)
            n = s.query(PairSession).filter(PairSession.id == sid, PairSession.active == True).update({"active": False})
            s.commit()
            return redirect("/admin/pairings", f"Sessões desconectadas: {n}")
        finally:
            s.close()

    @app.post("/admin/pairings/disconnect-room")
    async def admin_disconnect_room(request: Request):
        require_login(request)
        data = await form_data(request)
        s = db()
        try:
            r = s.scalar(select(Room).where(Room.room_number == data.get("room", "")))
            if not r:
                return redirect("/admin/pairings", "Quarto não encontrado")
            n = s.query(PairSession).filter(PairSession.room_id == r.id, PairSession.active == True).update({"active": False})
            s.commit()
            return redirect("/admin/pairings", f"Hóspedes desconectados do quarto {r.room_number}: {n}")
        finally:
            s.close()

    @app.post("/admin/pairings/disconnect-all")
    async def admin_disconnect_all(request: Request):
        require_login(request)
        s = db()
        try:
            n = s.query(PairSession).filter(PairSession.active == True).update({"active": False})
            s.commit()
            return redirect("/admin/pairings", f"Todos desconectados. Sessões fechadas: {n}")
        finally:
            s.close()

    @app.get("/admin/diagnostic", response_class=HTMLResponse)
    async def admin_diag(request: Request, msg: str = ""):
        user = require_login(request)
        s = db()
        try:
            rooms = list(s.scalars(select(Room)))
            sessions = list(s.scalars(select(PairSession).where(PairSession.active == True)))
            pairs = []
            for ps in sessions:
                r = s.get(Room, ps.room_id)
                if r and r.enabled:
                    pairs.append({"guest_ip": ps.guest_ip, "room_number": r.room_number, "cast_ip": r.cast_ip, "cast_name": r.cast_name, "expires_at": ps.expires_at.isoformat()})
            body = f"""
            <div class="card"><h2>Status</h2><p>Backend: <span class="badgetxt active">online</span></p><p>PUBLIC_BASE_URL: <span class="mono">{e(PUBLIC_BASE_URL)}</span></p><p>Quartos cadastrados: {len(rooms)}</p><p>Pareamentos ativos: {len(sessions)}</p></div>
            <div class="card"><h2>ACL atual</h2><pre class="mono">{e(pairs)}</pre></div>
            <div class="card"><h2>Comandos úteis no servidor</h2><pre class="mono">curl http://127.0.0.1:8080/health
curl -H "x-admin-token: $ADMIN_TOKEN" http://127.0.0.1:8080/admin/rooms
curl -H "x-gateway-token: $GATEWAY_TOKEN" http://127.0.0.1:8080/api/acl.json</pre></div>
            """
            return page("Diagnóstico", body, user, msg)
        finally:
            s.close()
