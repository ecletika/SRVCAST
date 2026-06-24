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
app=FastAPI(title='SRVCAST HotelCast Gateway', version='0.1.0')

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

@app.get('/health')
def health(): return {'ok':True,'time':now().isoformat()}

@app.post('/admin/rooms', dependencies=[Depends(check_admin)])
def create_room(r:RoomIn, s:Session=Depends(db)):
    room=s.scalar(select(Room).where(Room.room_number==r.room_number))
    if room:
        room.cast_name=r.cast_name; room.cast_ip=r.cast_ip; room.cast_mac=r.cast_mac; room.enabled=r.enabled
    else:
        room=Room(**r.model_dump()); s.add(room)
    s.commit(); s.refresh(room); return {'room_number':room.room_number,'cast_name':room.cast_name,'cast_ip':room.cast_ip,'enabled':room.enabled}

@app.get('/admin/rooms', dependencies=[Depends(check_admin)])
def rooms(s:Session=Depends(db)):
    return [{'room_number':r.room_number,'cast_name':r.cast_name,'cast_ip':r.cast_ip,'enabled':r.enabled} for r in s.scalars(select(Room).order_by(Room.room_number))]

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
