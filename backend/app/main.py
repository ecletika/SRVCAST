import io, os, secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import qrcode
import qrcode.image.svg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///./hotelcast.db')
ADMIN_TOKEN=os.getenv('ADMIN_TOKEN','troca-este-token-admin')
GATEWAY_TOKEN=os.getenv('GATEWAY_TOKEN','troca-este-token-gateway')
PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL','http://localhost:8080').rstrip('/')
SESSION_TTL_HOURS=int(os.getenv('SESSION_TTL_HOURS','24'))
TOKEN_TTL_MINUTES=int(os.getenv('TOKEN_TTL_MINUTES','60'))

class Base(DeclarativeBase): pass
engine=create_engine(DATABASE_URL, connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal=sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Room(Base):
    __tablename__='rooms'
    id=Column(Integer, primary_key=True)
    room_number=Column(String, unique=True, index=True, nullable=False)
    cast_name=Column(String, nullable=False)
    cast_ip=Column(String, nullable=False)
    cast_mac=Column(String, nullable=True)
    enabled=Column(Boolean, default=True)
class PairToken(Base):
    __tablename__='pair_tokens'
    id=Column(Integer, primary_key=True)
    token=Column(String, unique=True, index=True, nullable=False)
    room_id=Column(Integer, ForeignKey('rooms.id'), nullable=False)
    expires_at=Column(DateTime(timezone=True), nullable=False)
    used=Column(Boolean, default=False)
class PairSession(Base):
    __tablename__='pair_sessions'
    id=Column(Integer, primary_key=True)
    room_id=Column(Integer, ForeignKey('rooms.id'), nullable=False)
    guest_ip=Column(String, index=True, nullable=False)
    expires_at=Column(DateTime(timezone=True), nullable=False)
    active=Column(Boolean, default=True)

class RoomIn(BaseModel):
    room_number:str; cast_name:str; cast_ip:str; cast_mac:Optional[str]=None; enabled:bool=True

Base.metadata.create_all(bind=engine)
app=FastAPI(title='SRVCAST HotelCast Gateway', version='0.2.0')

def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()
def now(): return datetime.now(timezone.utc)
def check_admin(x_admin_token: str=Header(default='')):
    if x_admin_token!=ADMIN_TOKEN: raise HTTPException(401,'admin token inválido')
def check_gateway(x_gateway_token: str=Header(default='')):
    if x_gateway_token!=GATEWAY_TOKEN: raise HTTPException(401,'gateway token inválido')
def ip(req:Request):
    return (req.headers.get('x-forwarded-for') or (req.client.host if req.client else '0.0.0.0')).split(',')[0].strip()
def cleanup(s:Session):
    s.query(PairSession).filter(PairSession.expires_at<=now(), PairSession.active==True).update({'active':False}); s.commit()

ADMIN_UI_HTML='''<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SRVCAST Admin</title>
<style>
:root{--bg:#0f172a;--card:#111827;--muted:#94a3b8;--text:#e5e7eb;--line:#273449;--ok:#22c55e;--bad:#ef4444;--btn:#2563eb;--warn:#f59e0b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif}.wrap{max-width:1180px;margin:auto;padding:24px}h1{margin:0 0 8px}p{color:var(--muted)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:14px 0}input,textarea,select{width:100%;padding:10px;border-radius:9px;border:1px solid var(--line);background:#0b1220;color:var(--text)}textarea{min-height:120px}label{font-size:12px;color:var(--muted);display:block;margin:8px 0 4px}button,.button{background:var(--btn);color:white;border:0;border-radius:9px;padding:9px 12px;cursor:pointer;text-decoration:none;display:inline-block;margin:3px}.secondary{background:#334155}.danger{background:var(--bad)}.ok{background:var(--ok);color:#052e16}.warn{background:var(--warn);color:#111827}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}th{color:var(--muted);font-weight:normal}.row{display:grid;grid-template-columns:1fr 1fr 1.2fr 1fr .7fr 1.8fr;gap:8px;align-items:end}.status{padding:10px;border-radius:9px;background:#0b1220;margin-top:10px;white-space:pre-wrap}.small{font-size:12px;color:var(--muted)}@media(max-width:900px){.grid,.row{grid-template-columns:1fr}table{font-size:13px}}
</style>
</head>
<body>
<div class="wrap">
  <h1>SRVCAST Admin</h1>
  <p>Painel para gerir quartos, nomes e IPs dos Chromecasts. Base pública: <b id="base"></b></p>

  <div class="card">
    <label>Admin token</label>
    <div class="row" style="grid-template-columns:1fr auto auto">
      <input id="token" placeholder="cole o ADMIN_TOKEN aqui">
      <button onclick="saveToken()">Guardar token</button>
      <button class="secondary" onclick="loadRooms()">Atualizar</button>
    </div>
    <div class="small">Dica: pode abrir <code>/admin-ui?token=SEU_TOKEN</code>. Depois o navegador guarda localmente.</div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Criar ou atualizar quarto</h2>
      <label>Número/nome do quarto</label><input id="room_number" placeholder="Ex: 101, 205A, Suite Azul">
      <label>Nome do Cast</label><input id="cast_name" placeholder="Ex: Chromecast-101">
      <label>IP do Chromecast</label><input id="cast_ip" placeholder="Ex: 10.60.0.101">
      <label>MAC opcional</label><input id="cast_mac" placeholder="opcional">
      <label>Ativo</label><select id="enabled"><option value="true">Sim</option><option value="false">Não</option></select>
      <button onclick="saveRoom()">Salvar quarto</button>
      <button class="secondary" onclick="clearForm()">Limpar</button>
    </div>

    <div class="card">
      <h2>Importar vários quartos</h2>
      <p>Uma linha por quarto: <code>quarto;nome_cast;ip_cast</code>. Os quartos não precisam ser seguidos.</p>
      <textarea id="bulk" placeholder="101;Chromecast-101;10.60.0.101\n103;Chromecast-103;10.60.0.103\nSuite Azul;Chromecast-Suite-Azul;10.60.0.150"></textarea>
      <button onclick="bulkImport()">Importar/atualizar</button>
    </div>
  </div>

  <div class="card">
    <h2>Quartos cadastrados</h2>
    <table>
      <thead><tr><th>Quarto</th><th>Cast</th><th>IP</th><th>Status</th><th>Ações</th></tr></thead>
      <tbody id="rooms"><tr><td colspan="5">Clique em Atualizar.</td></tr></tbody>
    </table>
  </div>

  <div class="card">
    <h2>Sessões ativas</h2>
    <button class="secondary" onclick="loadAcl()">Ver hóspedes pareados</button>
    <pre id="acl" class="status">Ainda não carregado.</pre>
  </div>

  <div id="status" class="status">Pronto.</div>
</div>
<script>
const PUBLIC_BASE_URL='__PUBLIC_BASE_URL__';
document.getElementById('base').textContent=PUBLIC_BASE_URL;
function qs(name){return new URLSearchParams(location.search).get(name)}
const tokenFromUrl=qs('token');
if(tokenFromUrl){localStorage.setItem('srvcast_admin_token', tokenFromUrl)}
document.getElementById('token').value=localStorage.getItem('srvcast_admin_token')||'';
function token(){return document.getElementById('token').value.trim()}
function saveToken(){localStorage.setItem('srvcast_admin_token', token()); status('Token guardado.'); loadRooms()}
function status(msg){document.getElementById('status').textContent=msg}
async function api(path, opts={}){
  opts.headers=opts.headers||{};
  opts.headers['x-admin-token']=token();
  if(opts.body && !opts.headers['Content-Type']) opts.headers['Content-Type']='application/json';
  const r=await fetch(path, opts);
  const text=await r.text();
  if(!r.ok) throw new Error(text||r.statusText);
  try{return JSON.parse(text)}catch{return text}
}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function clearForm(){['room_number','cast_name','cast_ip','cast_mac'].forEach(id=>document.getElementById(id).value='');document.getElementById('enabled').value='true'}
function editRoom(r){document.getElementById('room_number').value=r.room_number;document.getElementById('cast_name').value=r.cast_name;document.getElementById('cast_ip').value=r.cast_ip;document.getElementById('cast_mac').value=r.cast_mac||'';document.getElementById('enabled').value=String(!!r.enabled);scrollTo(0,0)}
async function saveRoom(){
  const payload={room_number:room_number.value.trim(),cast_name:cast_name.value.trim(),cast_ip:cast_ip.value.trim(),cast_mac:cast_mac.value.trim()||null,enabled:enabled.value==='true'};
  if(!payload.room_number||!payload.cast_name||!payload.cast_ip){status('Preencha quarto, nome do Cast e IP.');return}
  await api('/admin/rooms',{method:'POST',body:JSON.stringify(payload)});
  status('Quarto salvo: '+payload.room_number); clearForm(); loadRooms();
}
async function loadRooms(){
  try{
    const data=await api('/admin/rooms');
    const tb=document.getElementById('rooms');
    if(!data.length){tb.innerHTML='<tr><td colspan="5">Nenhum quarto cadastrado.</td></tr>';return}
    tb.innerHTML=data.map(r=>`<tr><td><b>${esc(r.room_number)}</b></td><td>${esc(r.cast_name)}</td><td>${esc(r.cast_ip)}</td><td>${r.enabled?'Ativo':'Desativado'}</td><td><button onclick='editRoom(${JSON.stringify(r).replaceAll("'",'&#39;')})'>Editar</button><a class="button secondary" target="_blank" href="/tv/${encodeURIComponent(r.room_number)}">TV/QR</a><button class="warn" onclick="checkout('${esc(r.room_number)}')">Checkout</button><button class="danger" onclick='disableRoom(${JSON.stringify(r).replaceAll("'",'&#39;')})'>Desativar</button></td></tr>`).join('');
    status('Quartos carregados: '+data.length);
  }catch(e){status('Erro ao carregar quartos: '+e.message)}
}
async function disableRoom(r){r.enabled=false;await api('/admin/rooms',{method:'POST',body:JSON.stringify(r)});status('Quarto desativado: '+r.room_number);loadRooms()}
async function checkout(room){await api('/admin/checkout/'+encodeURIComponent(room),{method:'POST'});status('Checkout feito no quarto '+room);loadAcl()}
async function loadAcl(){
  try{
    const r=await fetch('/api/acl.json',{headers:{'x-gateway-token':'__GATEWAY_TOKEN_PLACEHOLDER__'}});
    document.getElementById('acl').textContent='Use no terminal para ver ACL completa:\n\ncurl -H "x-gateway-token: GATEWAY_TOKEN" http://127.0.0.1:8080/api/acl.json';
    if(r.ok) document.getElementById('acl').textContent=JSON.stringify(await r.json(),null,2);
  }catch(e){document.getElementById('acl').textContent='ACL não carregada pelo painel. Use o comando curl no servidor.'}
}
async function bulkImport(){
  const lines=document.getElementById('bulk').value.split(/\n+/).map(x=>x.trim()).filter(Boolean);
  let ok=0, errors=[];
  for(const line of lines){
    const p=line.split(/[;,]/).map(x=>x.trim());
    if(p.length<3){errors.push('Linha inválida: '+line);continue}
    try{await api('/admin/rooms',{method:'POST',body:JSON.stringify({room_number:p[0],cast_name:p[1],cast_ip:p[2],cast_mac:p[3]||null,enabled:true})});ok++}catch(e){errors.push(line+' -> '+e.message)}
  }
  status('Importados/atualizados: '+ok+(errors.length?'\nErros:\n'+errors.join('\n'):'')); loadRooms();
}
loadRooms();
</script>
</body>
</html>'''

@app.get('/', response_class=HTMLResponse)
def home():
    return f'''<html><body style="font-family:Arial;background:#111;color:white;padding:40px"><h1>SRVCAST</h1><p>Backend online.</p><p><a style="color:#93c5fd" href="/admin-ui">Abrir painel admin</a></p><p>Health: <a style="color:#93c5fd" href="/health">/health</a></p></body></html>'''

@app.get('/admin-ui', response_class=HTMLResponse)
def admin_ui():
    html=ADMIN_UI_HTML.replace('__PUBLIC_BASE_URL__', PUBLIC_BASE_URL)
    html=html.replace('__GATEWAY_TOKEN_PLACEHOLDER__', GATEWAY_TOKEN)
    return html

@app.get('/health')
def health(): return {'ok':True,'time':now().isoformat()}

@app.post('/admin/rooms', dependencies=[Depends(check_admin)])
def create_room(r:RoomIn, s:Session=Depends(db)):
    room=s.scalar(select(Room).where(Room.room_number==r.room_number))
    if room:
        room.cast_name=r.cast_name; room.cast_ip=r.cast_ip; room.cast_mac=r.cast_mac; room.enabled=r.enabled
    else:
        room=Room(**r.model_dump()); s.add(room)
    s.commit(); s.refresh(room); return {'room_number':room.room_number,'cast_name':room.cast_name,'cast_ip':room.cast_ip,'cast_mac':room.cast_mac,'enabled':room.enabled}

@app.get('/admin/rooms', dependencies=[Depends(check_admin)])
def rooms(s:Session=Depends(db)):
    return [{'room_number':r.room_number,'cast_name':r.cast_name,'cast_ip':r.cast_ip,'cast_mac':r.cast_mac,'enabled':r.enabled} for r in s.scalars(select(Room).order_by(Room.room_number))]

@app.get('/tv/{room_number}', response_class=HTMLResponse)
def tv(room_number:str, s:Session=Depends(db)):
    room=s.scalar(select(Room).where(Room.room_number==room_number, Room.enabled==True))
    if not room: raise HTTPException(404,'quarto não encontrado')
    token=secrets.token_urlsafe(32); exp=now()+timedelta(minutes=TOKEN_TTL_MINUTES)
    s.add(PairToken(token=token, room_id=room.id, expires_at=exp)); s.commit()
    return f'''<html><head><meta http-equiv="refresh" content="300"><style>body{{background:#111;color:white;font-family:Arial;display:flex;align-items:center;justify-content:center;height:100vh}}.c{{text-align:center}}img{{background:white;padding:20px;width:320px}}</style></head><body><div class="c"><h1>Quarto {room.room_number}</h1><p>Escaneie para liberar o Cast deste quarto</p><img src="/qr/{token}.svg"><p>{PUBLIC_BASE_URL}/pair/{token}</p></div></body></html>'''

@app.get('/qr/{token}.svg')
def qr(token:str):
    img=qrcode.make(f'{PUBLIC_BASE_URL}/pair/{token}', image_factory=qrcode.image.svg.SvgImage)
    buf=io.BytesIO(); img.save(buf); return Response(buf.getvalue(), media_type='image/svg+xml')

@app.get('/pair/{token}', response_class=HTMLResponse)
def pair(token:str, req:Request, s:Session=Depends(db)):
    t=s.scalar(select(PairToken).where(PairToken.token==token, PairToken.used==False))
    if not t or t.expires_at.replace(tzinfo=timezone.utc)<now(): raise HTTPException(400,'QR expirado')
    guest=ip(req); exp=now()+timedelta(hours=SESSION_TTL_HOURS)
    s.query(PairSession).filter(PairSession.guest_ip==guest, PairSession.active==True).update({'active':False})
    s.add(PairSession(room_id=t.room_id, guest_ip=guest, expires_at=exp)); t.used=True; s.commit()
    room=s.get(Room,t.room_id)
    return f'<html><body><h1>Cast liberado</h1><p>IP {guest} autorizado para o quarto {room.room_number}.</p><p>Abra o YouTube/Netflix e use o botão Cast.</p></body></html>'

@app.post('/admin/checkout/{room_number}', dependencies=[Depends(check_admin)])
def checkout(room_number:str, s:Session=Depends(db)):
    room=s.scalar(select(Room).where(Room.room_number==room_number))
    if not room: raise HTTPException(404,'quarto não encontrado')
    n=s.query(PairSession).filter(PairSession.room_id==room.id, PairSession.active==True).update({'active':False}); s.commit(); return {'room':room_number,'closed_sessions':n}

@app.get('/api/acl.json', dependencies=[Depends(check_gateway)])
def acl(s:Session=Depends(db)):
    cleanup(s); rows=[]
    for ps in s.scalars(select(PairSession).where(PairSession.active==True)):
        r=s.get(Room, ps.room_id)
        if r and r.enabled: rows.append({'guest_ip':ps.guest_ip,'room_number':r.room_number,'cast_ip':r.cast_ip,'cast_name':r.cast_name,'expires_at':ps.expires_at.isoformat()})
    return {'pairs':rows}
