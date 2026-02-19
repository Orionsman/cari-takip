"""
Cari Hesap Takip - PWA / Bulut Sürümü
PostgreSQL Production Version
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import psycopg2
from psycopg2 import errors
import requests
from datetime import datetime

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
PORT = int(os.environ.get("PORT", 5000))
BUCKET = "db-backups"

# ── Veritabanı ─────────────────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    conn.autocommit = True
    return conn

def rows_to_dicts(cur):
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cariler (
                id SERIAL PRIMARY KEY,
                firma_adi TEXT NOT NULL, yetkili TEXT,
                telefon TEXT, email TEXT, adres TEXT, notlar TEXT
            );
            CREATE TABLE IF NOT EXISTS urunler (
                id SERIAL PRIMARY KEY, kod TEXT,
                ad TEXT NOT NULL, birim TEXT DEFAULT 'Adet',
                fiyat NUMERIC DEFAULT 0, stok NUMERIC DEFAULT 0, notlar TEXT
            );
            CREATE TABLE IF NOT EXISTS hareketler (
                id SERIAL PRIMARY KEY,
                cari_id INTEGER NOT NULL REFERENCES cariler(id) ON DELETE CASCADE,
                tarih TEXT NOT NULL, aciklama TEXT,
                borc NUMERIC DEFAULT 0, alacak NUMERIC DEFAULT 0,
                tur TEXT DEFAULT 'manuel', ref_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS satislar (
                id SERIAL PRIMARY KEY,
                cari_id INTEGER NOT NULL REFERENCES cariler(id) ON DELETE CASCADE,
                urun_id INTEGER NOT NULL REFERENCES urunler(id) ON DELETE RESTRICT,
                tarih TEXT NOT NULL, adet NUMERIC NOT NULL,
                birim_fiyat NUMERIC NOT NULL, toplam NUMERIC NOT NULL, aciklama TEXT
            );
            CREATE TABLE IF NOT EXISTS odemeler (
                id SERIAL PRIMARY KEY,
                cari_id INTEGER NOT NULL REFERENCES cariler(id) ON DELETE CASCADE,
                tarih TEXT NOT NULL, tutar NUMERIC NOT NULL,
                yontem TEXT DEFAULT 'Nakit', aciklama TEXT
            );
        """)

# ── Backup ─────────────────────────────────────────────────────────────────────

def create_backup():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.sql"
    filepath = f"/tmp/{filename}"
    with get_db() as conn:
        cur = conn.cursor()
        with open(filepath, "w", encoding="utf-8") as f:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            for (table,) in cur.fetchall():
                f.write(f"\n-- TABLE: {table}\n")
                cur.execute(f"SELECT * FROM {table}")
                for row in cur.fetchall():
                    vals = []
                    for v in row:
                        if v is None: vals.append("NULL")
                        elif isinstance(v, str): vals.append("'" + v.replace("'","''") + "'")
                        else: vals.append(str(v))
                    f.write(f"INSERT INTO {table} VALUES ({', '.join(vals)});\n")
    return filename, filepath

def upload_to_supabase(filename, path):
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{filename}"
    headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "text/plain"}
    with open(path, "rb") as f:
        r = requests.post(url, headers=headers, data=f)
    if r.status_code not in [200, 201]:
        raise Exception(r.text)

@app.route("/backup-now")
def manual_backup():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return jsonify({"error": "Supabase config missing"}), 500
        filename, path = create_backup()
        upload_to_supabase(filename, path)
        return jsonify({"status": "Backup uploaded", "file": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/restore/<filename>")
def restore_backup(filename):
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return jsonify({"error": "Supabase config missing"}), 500
        r = requests.get(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{filename}",
                         headers={"Authorization": f"Bearer {SUPABASE_KEY}"})
        if r.status_code != 200:
            return jsonify({"error": "Backup file not found"}), 404
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("TRUNCATE TABLE hareketler,satislar,odemeler,urunler,cariler RESTART IDENTITY CASCADE;")
            for cmd in r.text.split(";"):
                cmd = cmd.strip()
                if cmd: cur.execute(cmd)
        return jsonify({"status": "Restore completed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/backups")
def list_backups():
    return "BACKUPS V2 CALISIYOR"

# ── PWA ────────────────────────────────────────────────────────────────────────

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")

@app.route("/sw.js")
def sw():
    resp = send_from_directory("static", "sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Content-Type"] = "application/javascript"
    return resp

@app.route("/")
def index():
    return render_template("index.html")

# ── Cariler ────────────────────────────────────────────────────────────────────

@app.route("/api/cariler")
def api_cariler():
    q = request.args.get("q", "")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM cariler WHERE firma_adi ILIKE %s ORDER BY firma_adi", (f"%{q}%",))
        return jsonify(rows_to_dicts(cur))

@app.route("/api/cariler", methods=["POST"])
def api_cari_ekle():
    d = request.json
    if not d.get("firma_adi"):
        return jsonify({"error": "Firma adı zorunludur"}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO cariler (firma_adi,yetkili,telefon,email,adres,notlar) VALUES (%s,%s,%s,%s,%s,%s)",
            (d["firma_adi"],d.get("yetkili",""),d.get("telefon",""),d.get("email",""),d.get("adres",""),d.get("notlar","")))
    return jsonify({"ok": True})

@app.route("/api/cariler/<int:cid>", methods=["PUT"])
def api_cari_guncelle(cid):
    d = request.json
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE cariler SET firma_adi=%s,yetkili=%s,telefon=%s,email=%s,adres=%s,notlar=%s WHERE id=%s",
            (d["firma_adi"],d.get("yetkili",""),d.get("telefon",""),d.get("email",""),d.get("adres",""),d.get("notlar",""),cid))
    return jsonify({"ok": True})

@app.route("/api/cariler/<int:cid>", methods=["DELETE"])
def api_cari_sil(cid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM cariler WHERE id=%s", (cid,))
    return jsonify({"ok": True})

@app.route("/api/cariler/<int:cid>/ozet")
def api_cari_ozet(cid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(borc),0),COALESCE(SUM(alacak),0) FROM hareketler WHERE cari_id=%s", (cid,))
        b, a = cur.fetchone()
    return jsonify({"borc": float(b), "alacak": float(a), "bakiye": float(b)-float(a)})

# ── Hareketler ─────────────────────────────────────────────────────────────────

@app.route("/api/hareketler/<int:cid>")
def api_hareketler(cid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM hareketler WHERE cari_id=%s ORDER BY tarih,id", (cid,))
        rows = rows_to_dicts(cur)
    result, bakiye = [], 0
    for r in rows:
        bakiye += float(r["borc"]) - float(r["alacak"])
        r["bakiye"] = bakiye
        result.append(r)
    return jsonify(result)

@app.route("/api/hareketler", methods=["POST"])
def api_hareket_ekle():
    d = request.json
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO hareketler (cari_id,tarih,aciklama,borc,alacak,tur) VALUES (%s,%s,%s,%s,%s,'manuel')",
            (d["cari_id"],d["tarih"],d.get("aciklama",""),float(d.get("borc",0)),float(d.get("alacak",0))))
    return jsonify({"ok": True})

@app.route("/api/hareketler/<int:hid>", methods=["DELETE"])
def api_hareket_sil(hid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM hareketler WHERE id=%s", (hid,))
    return jsonify({"ok": True})

# ── Ürünler ────────────────────────────────────────────────────────────────────

@app.route("/api/urunler")
def api_urunler():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM urunler ORDER BY ad")
        return jsonify(rows_to_dicts(cur))

@app.route("/api/urunler", methods=["POST"])
def api_urun_ekle():
    d = request.json
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO urunler (ad,kod,birim,fiyat,stok,notlar) VALUES (%s,%s,%s,%s,%s,%s)",
            (d["ad"],d.get("kod",""),d.get("birim","Adet"),float(d.get("fiyat",0)),float(d.get("stok",0)),d.get("notlar","")))
    return jsonify({"ok": True})

@app.route("/api/urunler/<int:uid>", methods=["PUT"])
def api_urun_guncelle(uid):
    d = request.json
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE urunler SET ad=%s,kod=%s,birim=%s,fiyat=%s,stok=%s,notlar=%s WHERE id=%s",
            (d["ad"],d.get("kod",""),d.get("birim","Adet"),float(d.get("fiyat",0)),float(d.get("stok",0)),d.get("notlar",""),uid))
    return jsonify({"ok": True})

@app.route("/api/urunler/<int:uid>", methods=["DELETE"])
def api_urun_sil(uid):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM urunler WHERE id=%s", (uid,))
        return jsonify({"ok": True})
    except errors.ForeignKeyViolation:
        return jsonify({"error": "Ürün satışlarda kullanılıyor, silinemez"}), 400

# ── Satışlar ───────────────────────────────────────────────────────────────────

@app.route("/api/satislar")
def api_satislar():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT s.*,c.firma_adi,u.ad as urun_adi FROM satislar s
            JOIN cariler c ON s.cari_id=c.id JOIN urunler u ON s.urun_id=u.id
            ORDER BY s.tarih DESC,s.id DESC""")
        return jsonify(rows_to_dicts(cur))

@app.route("/api/satislar", methods=["POST"])
def api_satis_ekle():
    d = request.json
    adet, fiyat = float(d["adet"]), float(d["birim_fiyat"])
    toplam = adet * fiyat
    hr = f"Satış: {d.get('urun_adi','Ürün')} x{adet:g} @ {fiyat:,.2f}₺"
    if d.get("aciklama"): hr += f" – {d['aciklama']}"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO satislar (cari_id,urun_id,tarih,adet,birim_fiyat,toplam,aciklama) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (d["cari_id"],d["urun_id"],d["tarih"],adet,fiyat,toplam,d.get("aciklama","")))
        cur.execute("INSERT INTO hareketler (cari_id,tarih,aciklama,borc,alacak,tur) VALUES (%s,%s,%s,%s,0,'satış')",
            (d["cari_id"],d["tarih"],hr,toplam))
    return jsonify({"ok": True, "toplam": toplam})

@app.route("/api/satislar/<int:sid>", methods=["DELETE"])
def api_satis_sil(sid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT cari_id,tarih,toplam FROM satislar WHERE id=%s", (sid,))
        r = cur.fetchone()
        if r:
            cur.execute("DELETE FROM hareketler WHERE cari_id=%s AND tarih=%s AND borc=%s AND tur='satış'", r)
        cur.execute("DELETE FROM satislar WHERE id=%s", (sid,))
    return jsonify({"ok": True})

# ── Ödemeler ───────────────────────────────────────────────────────────────────

@app.route("/api/odemeler")
def api_odemeler():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT o.*,c.firma_adi FROM odemeler o
            JOIN cariler c ON o.cari_id=c.id ORDER BY o.tarih DESC,o.id DESC""")
        return jsonify(rows_to_dicts(cur))

@app.route("/api/odemeler", methods=["POST"])
def api_odeme_ekle():
    d = request.json
    tutar = float(d["tutar"])
    hr = f"Ödeme ({d.get('yontem','Nakit')})"
    if d.get("aciklama"): hr += f" – {d['aciklama']}"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO odemeler (cari_id,tarih,tutar,yontem,aciklama) VALUES (%s,%s,%s,%s,%s)",
            (d["cari_id"],d["tarih"],tutar,d.get("yontem","Nakit"),d.get("aciklama","")))
        cur.execute("INSERT INTO hareketler (cari_id,tarih,aciklama,borc,alacak,tur) VALUES (%s,%s,%s,0,%s,'ödeme')",
            (d["cari_id"],d["tarih"],hr,tutar))
    return jsonify({"ok": True})

@app.route("/api/odemeler/<int:oid>", methods=["DELETE"])
def api_odeme_sil(oid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT cari_id,tarih,tutar FROM odemeler WHERE id=%s", (oid,))
        r = cur.fetchone()
        if r:
            cur.execute("DELETE FROM hareketler WHERE cari_id=%s AND tarih=%s AND alacak=%s AND tur='ödeme'", r)
        cur.execute("DELETE FROM odemeler WHERE id=%s", (oid,))
    return jsonify({"ok": True})

# ── Başlat ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(f"✓ Sunucu başlatıldı → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)

init_db()
