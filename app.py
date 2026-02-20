"""
Cari Hesap Takip - Flask Web Uygulaması
Çalıştır: python app.py
Tarayıcıda aç: http://BILGISAYAR_IP:5000
"""

from flask import Flask, render_template, request, jsonify
import sqlite3, os

app = Flask(__name__)
DB_FILE = os.path.join(os.path.dirname(__file__), "cari_hesap.db")

# ── Veritabanı ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cariler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firma_adi TEXT NOT NULL, yetkili TEXT,
                telefon TEXT, email TEXT, adres TEXT, notlar TEXT
            );
            CREATE TABLE IF NOT EXISTS urunler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kod TEXT, ad TEXT NOT NULL, birim TEXT DEFAULT 'Adet',
                fiyat REAL DEFAULT 0, stok REAL DEFAULT 0, notlar TEXT
            );
            CREATE TABLE IF NOT EXISTS hareketler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cari_id INTEGER NOT NULL, tarih TEXT NOT NULL,
                aciklama TEXT, borc REAL DEFAULT 0, alacak REAL DEFAULT 0,
                tur TEXT DEFAULT 'manuel', ref_id INTEGER,
                FOREIGN KEY (cari_id) REFERENCES cariler(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS satislar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cari_id INTEGER NOT NULL, urun_id INTEGER NOT NULL,
                tarih TEXT NOT NULL, adet REAL NOT NULL,
                birim_fiyat REAL NOT NULL, toplam REAL NOT NULL, aciklama TEXT,
                FOREIGN KEY (cari_id) REFERENCES cariler(id) ON DELETE CASCADE,
                FOREIGN KEY (urun_id) REFERENCES urunler(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS odemeler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cari_id INTEGER NOT NULL, tarih TEXT NOT NULL,
                tutar REAL NOT NULL, yontem TEXT DEFAULT 'Nakit', aciklama TEXT,
                FOREIGN KEY (cari_id) REFERENCES cariler(id) ON DELETE CASCADE
            );
        """)
        for sql in [
            "ALTER TABLE hareketler ADD COLUMN tur TEXT DEFAULT 'manuel'",
            "ALTER TABLE hareketler ADD COLUMN ref_id INTEGER",
        ]:
            try: conn.execute(sql)
            except: pass
        conn.commit()

# ── Sayfalar ───────────────────────────────────────────────────────────────────

@app.route("/")
def index(): return render_template("index.html")

# ── API: Cariler ───────────────────────────────────────────────────────────────

@app.route("/api/cariler")
def api_cariler():
    q = request.args.get("q", "")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM cariler WHERE firma_adi LIKE ? ORDER BY firma_adi",
            (f"%{q}%",)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/cariler", methods=["POST"])
def api_cari_ekle():
    d = request.json
    if not d.get("firma_adi"):
        return jsonify({"error": "Firma adı zorunludur"}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT INTO cariler (firma_adi,yetkili,telefon,email,adres,notlar) VALUES (?,?,?,?,?,?)",
            (d["firma_adi"], d.get("yetkili",""), d.get("telefon",""),
             d.get("email",""), d.get("adres",""), d.get("notlar","")))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/cariler/<int:cid>", methods=["PUT"])
def api_cari_guncelle(cid):
    d = request.json
    with get_db() as conn:
        conn.execute(
            "UPDATE cariler SET firma_adi=?,yetkili=?,telefon=?,email=?,adres=?,notlar=? WHERE id=?",
            (d["firma_adi"], d.get("yetkili",""), d.get("telefon",""),
             d.get("email",""), d.get("adres",""), d.get("notlar",""), cid))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/cariler/<int:cid>", methods=["DELETE"])
def api_cari_sil(cid):
    with get_db() as conn:
        conn.execute("DELETE FROM cariler WHERE id=?", (cid,))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/cariler/<int:cid>/ozet")
def api_cari_ozet(cid):
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(borc),0) as borc, COALESCE(SUM(alacak),0) as alacak "
            "FROM hareketler WHERE cari_id=?", (cid,)).fetchone()
    borc, alacak = row["borc"], row["alacak"]
    return jsonify({"borc": borc, "alacak": alacak, "bakiye": borc - alacak})

# ── API: Hareketler ────────────────────────────────────────────────────────────

@app.route("/api/hareketler/<int:cid>")
def api_hareketler(cid):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM hareketler WHERE cari_id=? ORDER BY tarih,id", (cid,)).fetchall()
    result, bakiye = [], 0
    for r in rows:
        r = dict(r)
        bakiye += r["borc"] - r["alacak"]
        r["bakiye"] = bakiye
        result.append(r)
    return jsonify(result)

@app.route("/api/hareketler", methods=["POST"])
def api_hareket_ekle():
    d = request.json
    with get_db() as conn:
        conn.execute(
            "INSERT INTO hareketler (cari_id,tarih,aciklama,borc,alacak,tur) VALUES (?,?,?,?,?,'manuel')",
            (d["cari_id"], d["tarih"], d.get("aciklama",""),
             float(d.get("borc",0)), float(d.get("alacak",0))))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/hareketler/<int:hid>", methods=["DELETE"])
def api_hareket_sil(hid):
    with get_db() as conn:
        conn.execute("DELETE FROM hareketler WHERE id=?", (hid,))
        conn.commit()
    return jsonify({"ok": True})

# ── API: Ürünler ───────────────────────────────────────────────────────────────

@app.route("/api/urunler")
def api_urunler():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/urunler", methods=["POST"])
def api_urun_ekle():
    d = request.json
    with get_db() as conn:
        conn.execute(
            "INSERT INTO urunler (ad,kod,birim,fiyat,stok,notlar) VALUES (?,?,?,?,?,?)",
            (d["ad"], d.get("kod",""), d.get("birim","Adet"),
             float(d.get("fiyat",0)), float(d.get("stok",0)), d.get("notlar","")))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/urunler/<int:uid>", methods=["PUT"])
def api_urun_guncelle(uid):
    d = request.json
    with get_db() as conn:
        conn.execute(
            "UPDATE urunler SET ad=?,kod=?,birim=?,fiyat=?,stok=?,notlar=? WHERE id=?",
            (d["ad"], d.get("kod",""), d.get("birim","Adet"),
             float(d.get("fiyat",0)), float(d.get("stok",0)), d.get("notlar",""), uid))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/urunler/<int:uid>", methods=["DELETE"])
def api_urun_sil(uid):
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM urunler WHERE id=?", (uid,))
            conn.commit()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Ürün satışlarda kullanılıyor"}), 400

# ── API: Satışlar ──────────────────────────────────────────────────────────────

@app.route("/api/satislar")
def api_satislar():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT s.*,c.firma_adi,u.ad as urun_adi FROM satislar s
            JOIN cariler c ON s.cari_id=c.id JOIN urunler u ON s.urun_id=u.id
            ORDER BY s.tarih DESC,s.id DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/satislar", methods=["POST"])
def api_satis_ekle():
    d = request.json
    adet, fiyat = float(d["adet"]), float(d["birim_fiyat"])
    toplam = adet * fiyat
    hr_acik = f"Satış: {d.get('urun_adi','Ürün')} x{adet:g} @ {fiyat:,.2f}₺"
    if d.get("aciklama"): hr_acik += f" – {d['aciklama']}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO satislar (cari_id,urun_id,tarih,adet,birim_fiyat,toplam,aciklama) VALUES (?,?,?,?,?,?,?)",
            (d["cari_id"], d["urun_id"], d["tarih"], adet, fiyat, toplam, d.get("aciklama","")))
        conn.execute(
            "INSERT INTO hareketler (cari_id,tarih,aciklama,borc,alacak,tur) VALUES (?,?,?,?,0,'satış')",
            (d["cari_id"], d["tarih"], hr_acik, toplam))
        conn.commit()
    return jsonify({"ok": True, "toplam": toplam})

@app.route("/api/satislar/<int:sid>", methods=["DELETE"])
def api_satis_sil(sid):
    with get_db() as conn:
        row = conn.execute("SELECT cari_id,tarih,toplam FROM satislar WHERE id=?", (sid,)).fetchone()
        if row:
            conn.execute(
                "DELETE FROM hareketler WHERE cari_id=? AND tarih=? AND borc=? AND tur='satış'",
                (row["cari_id"], row["tarih"], row["toplam"]))
        conn.execute("DELETE FROM satislar WHERE id=?", (sid,))
        conn.commit()
    return jsonify({"ok": True})

# ── API: Ödemeler ──────────────────────────────────────────────────────────────

@app.route("/api/odemeler")
def api_odemeler():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT o.*,c.firma_adi FROM odemeler o
            JOIN cariler c ON o.cari_id=c.id
            ORDER BY o.tarih DESC,o.id DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/odemeler", methods=["POST"])
def api_odeme_ekle():
    d = request.json
    tutar = float(d["tutar"])
    hr_acik = f"Ödeme ({d.get('yontem','Nakit')})"
    if d.get("aciklama"): hr_acik += f" – {d['aciklama']}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO odemeler (cari_id,tarih,tutar,yontem,aciklama) VALUES (?,?,?,?,?)",
            (d["cari_id"], d["tarih"], tutar, d.get("yontem","Nakit"), d.get("aciklama","")))
        conn.execute(
            "INSERT INTO hareketler (cari_id,tarih,aciklama,borc,alacak,tur) VALUES (?,?,?,0,?,'ödeme')",
            (d["cari_id"], d["tarih"], hr_acik, tutar))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/odemeler/<int:oid>", methods=["DELETE"])
def api_odeme_sil(oid):
    with get_db() as conn:
        row = conn.execute("SELECT cari_id,tarih,tutar FROM odemeler WHERE id=?", (oid,)).fetchone()
        if row:
            conn.execute(
                "DELETE FROM hareketler WHERE cari_id=? AND tarih=? AND alacak=? AND tur='ödeme'",
                (row["cari_id"], row["tarih"], row["tutar"]))
        conn.execute("DELETE FROM odemeler WHERE id=?", (oid,))
        conn.commit()
    return jsonify({"ok": True})

# ── Başlat ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = "127.0.0.1"
    print("=" * 55)
    print("  Cari Hesap Takip Sistemi başlatıldı!")
    print(f"  Bilgisayardan : http://localhost:5000")
    print(f"  Telefondan    : http://{local_ip}:5000")
    print("  (Telefon ve bilgisayar aynı WiFi'de olmalı)")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)
