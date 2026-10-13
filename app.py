import os
import sqlite3
import secrets
from datetime import datetime

from flask import (
    Flask, request, redirect, url_for, session,
    send_from_directory, render_template_string, flash, abort
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# Permanent storage in the script's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "store.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_APP_EXTENSIONS = {"apk"}
ALLOWED_ICON_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# File upload limit set to 2GB for large APKs like Termux
app.config["MAX_CONTENT_LENGTH"] = 2000 * 1024 * 1024 

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ---------------------------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price TEXT NOT NULL,
            rating REAL NOT NULL,
            description TEXT NOT NULL,
            icon_filename TEXT,
            file_filename TEXT NOT NULL,
            file_original_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            downloads INTEGER DEFAULT 150,
            reviews_count INTEGER DEFAULT 5,
            created_at TEXT NOT NULL
        )
    """)
    # Owner Profile Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS owner_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL,
            avatar_filename TEXT,
            password_hash TEXT
        )
    """)
    
    existing = conn.execute("SELECT id FROM owner_profile WHERE id = 1").fetchone()
    if not existing:
        default_pwd = generate_password_hash("naresh123")
        conn.execute(
            "INSERT INTO owner_profile (id, name, avatar_filename, password_hash) VALUES (1, ?, ?, ?)",
            ("Naresh XX", "", default_pwd)
        )
    conn.commit()
    conn.close()


def get_owner():
    conn = get_db()
    row = conn.execute("SELECT * FROM owner_profile WHERE id = 1").fetchone()
    conn.close()
    return row


def get_apps(tab="apps"):
    conn = get_db()
    if tab == "top":
        sql = "SELECT * FROM apps ORDER BY rating DESC"
    elif tab == "games":
        sql = "SELECT * FROM apps WHERE category = 'Games' ORDER BY created_at DESC"
    elif tab == "books":
        sql = "SELECT * FROM apps WHERE category = 'Books' ORDER BY created_at DESC"
    else:
        sql = "SELECT * FROM apps ORDER BY created_at DESC"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return rows


def format_size(num_bytes):
    if num_bytes is None:
        return ""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def allowed_file(filename, allowed_extensions):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_extensions


def fixed_rating_for(app_id):
    digest = sum(bytearray(app_id.encode("utf-8")))
    return round(3.5 + (digest % 16) / 10, 1)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    tab = request.args.get("tab", "apps")
    apps_rows = get_apps(tab=tab)
    owner = get_owner()
    return render_template_string(
        PAGE_TEMPLATE,
        apps=apps_rows,
        tab=tab,
        owner=owner,
        format_size=format_size
    )


@app.route("/upload", methods=["POST"])
def upload():
    try:
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "Tools")
        price = request.form.get("price", "").strip() or "Free"
        description = request.form.get("description", "").strip() or "My APK application."

        app_file = request.files.get("app_file")
        icon_file = request.files.get("icon_file")

        if not name:
            flash("❌ Please enter an app name.")
            return redirect(url_for("index"))
        if not app_file or app_file.filename == "":
            flash("❌ Please select an APK file to upload.")
            return redirect(url_for("index"))
        if not allowed_file(app_file.filename, ALLOWED_APP_EXTENSIONS):
            flash("❌ Only .apk files are allowed!")
            return redirect(url_for("index"))
        if icon_file and icon_file.filename != "" and not allowed_file(icon_file.filename, ALLOWED_ICON_EXTENSIONS):
            flash("❌ Invalid icon format.")
            return redirect(url_for("index"))

        app_id = "app_" + secrets.token_hex(8)
        file_filename = secure_filename(f"{app_id}_{app_file.filename}")
        save_path = os.path.join(UPLOAD_DIR, file_filename)
        app_file.save(save_path)
        file_size = os.path.getsize(save_path)

        icon_filename = None
        if icon_file and icon_file.filename != "":
            icon_filename = secure_filename(f"{app_id}_icon_{icon_file.filename}")
            icon_file.save(os.path.join(UPLOAD_DIR, icon_filename))

        rating = fixed_rating_for(app_id)

        conn = get_db()
        conn.execute(
            """INSERT INTO apps
               (id, name, category, price, rating, description, icon_filename,
                file_filename, file_original_name, file_size, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (app_id, name, category, price, rating, description, icon_filename,
             file_filename, app_file.filename, file_size, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()

        flash("✅ APK Uploaded Successfully!")
    except Exception as e:
        flash(f"❌ Error uploading file: {str(e)}")
    
    return redirect(url_for("index"))


@app.route("/profile/update", methods=["POST"])
def update_profile():
    password = request.form.get("owner_password", "")
    new_name = request.form.get("owner_name", "Naresh XX").strip()
    avatar_file = request.files.get("avatar_file")

    owner = get_owner()
    if not check_password_hash(owner["password_hash"], password):
        flash("❌ Wrong Owner Password! Profile cannot be changed. (Default is: naresh123)")
        return redirect(url_for("index"))

    avatar_filename = owner["avatar_filename"]
    if avatar_file and avatar_file.filename != "" and allowed_file(avatar_file.filename, ALLOWED_ICON_EXTENSIONS):
        avatar_filename = secure_filename(f"owner_avatar_{secrets.token_hex(4)}_{avatar_file.filename}")
        avatar_file.save(os.path.join(UPLOAD_DIR, avatar_filename))

    conn = get_db()
    conn.execute(
        "UPDATE owner_profile SET name = ?, avatar_filename = ? WHERE id = 1",
        (new_name, avatar_filename)
    )
    conn.commit()
    conn.close()

    flash("✅ Owner profile updated successfully!")
    return redirect(url_for("index"))


@app.route("/download/<app_id>")
def download(app_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
    if row:
        conn.execute("UPDATE apps SET downloads = downloads + 1 WHERE id = ?", (app_id,))
        conn.commit()
    conn.close()
    if not row:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR, row["file_filename"], as_attachment=True,
        download_name=row["file_original_name"]
    )


@app.route("/icon/<app_id>")
def icon(app_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
    conn.close()
    if not row or not row["icon_filename"]:
        abort(404)
    return send_from_directory(UPLOAD_DIR, row["icon_filename"])


@app.route("/avatar/<filename>")
def avatar_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------------------------------------------------------------------
# Frontend Template
# ---------------------------------------------------------------------------

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{{ owner['name'] }} — APK Store</title>
<style>
:root{
  --bg:#0a0716; --border:#3a2f6b; --text:#f8fbff; --muted:#b4a9d6;
  --blue:#00d4ff; --purple:#a855f7; --pink:#ff2d92; --green:#22e59a; --yellow:#ffd60a;
}
*{box-sizing:border-box}
body{
  margin:0;font-family:Inter,system-ui,sans-serif;color:var(--text);padding-bottom:90px;
  background:radial-gradient(circle at 10% 10%,#1e3fae66,transparent 25%),
             radial-gradient(circle at 90% 20%,#8a1fc966,transparent 25%),
             radial-gradient(circle at 50% 100%,#ff2d9233,transparent 30%),var(--bg);
}
a{color:inherit;text-decoration:none}
.store-header{position:sticky;top:0;z-index:50;background:linear-gradient(180deg,#1a1338,#150f2e 90%);
  border-bottom:1px solid var(--border);padding:14px 18px;}
.header-top{display:flex;align-items:center;justify-content:space-between;gap:12px;}
.logo-brand{display:flex;align-items:center;gap:12px;}
.owner-avatar-btn{width:46px;height:46px;border-radius:14px;border:2px solid var(--blue);overflow:hidden;cursor:pointer;
  background:linear-gradient(135deg,var(--blue),var(--purple),var(--pink));display:grid;place-items:center;padding:0;}
.owner-avatar-btn img{width:100%;height:100%;object-fit:cover;}
.owner-avatar-btn span{font-size:20px;font-weight:900;color:#fff;}
.logo-brand h1{font-size:18px;margin:0;}
.logo-brand h1 span{background:linear-gradient(90deg,var(--blue),var(--purple),var(--pink));
  -webkit-background-clip:text;color:transparent;}
.logo-brand p{margin:2px 0 0;color:var(--muted);font-size:12px;}
.search-row{margin-top:12px;}
.search-row input{width:100%;height:40px;border:1px solid var(--border);background:#160f30;color:#fff;
  border-radius:12px;padding:0 14px;outline:0;}
.content{padding:16px 14px 10px;max-width:1100px;margin:0 auto;}
.section-title{display:flex;align-items:center;gap:8px;margin:6px 0 14px;}
.section-title h2{font-size:18px;margin:0;}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:12px;}
.card{background:linear-gradient(145deg,#20134a,#15102f 55%,#241044);border:1px solid #5d43a8;
  border-radius:16px;padding:10px 8px;text-align:center;cursor:pointer;transition:transform 0.2s;}
.card:active{transform:scale(0.97);}
.thumb{width:100%;aspect-ratio:1/1;margin:0 auto 8px;border-radius:14px;overflow:hidden;display:grid;
  place-items:center;font-size:28px;background:radial-gradient(circle,#3a2f6b,#150f2e);}
.thumb img{width:100%;height:100%;object-fit:cover;}
.card h3{font-size:12px;margin:0 0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.card .rating{font-size:11px;color:var(--yellow);font-weight:600;}
.empty-store{margin-top:20px;padding:45px 20px;text-align:center;border:1px dashed #4a3b7a;
  border-radius:18px;background:linear-gradient(145deg,#160f30,#1c1030);}
.btn{border:0;border-radius:11px;padding:12px 20px;background:linear-gradient(90deg,var(--blue),var(--purple),var(--pink));
  color:#fff;font-weight:800;cursor:pointer;}
.cancel{border:1px solid #4a3b7a;background:transparent;color:#dbe4f2;border-radius:10px;padding:11px 17px;cursor:pointer;}
.modal{position:fixed;inset:0;background:#000d;display:none;place-items:center;z-index:300;padding:16px;}
.modal.show{display:grid;}
.modal-card{width:min(440px,100%);max-height:90vh;overflow:auto;background:linear-gradient(145deg,#1c1440,#120b2c);
  border:1px solid #5d43a8;border-radius:22px;padding:22px;}
.form-row{display:grid;gap:7px;margin:13px 0;}
.form-row label{font-size:13px;color:#c9bfe8;}
.form-row input,.form-row textarea,.form-row select{width:100%;border:1px solid #4a3b7a;background:#160f30;
  color:#fff;border-radius:10px;padding:11px;outline:none;}
.form-row textarea{min-height:80px;}
.modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:16px;flex-wrap:wrap;}
.flash{background:#1e1642;border:1px solid var(--blue);border-radius:10px;padding:12px 16px;margin:14px 0;font-size:14px;}
.fab{position:fixed;right:20px;bottom:85px;border-radius:50%;width:52px;height:52px;font-size:20px;
  background:linear-gradient(90deg,var(--blue),var(--purple));border:0;color:#fff;box-shadow:0 8px 22px #a855f755;cursor:pointer;z-index:40;}

/* Bottom Nav Bar */
.bottom-nav{position:fixed;bottom:0;left:0;right:0;height:70px;background:#120c29;border-top:1px solid var(--border);
  display:flex;justify-content:space-around;align-items:center;z-index:40;padding-bottom:env(safe-area-inset-bottom);}
.nav-item{display:flex;flex-direction:column;align-items:center;gap:3px;color:var(--muted);font-size:11px;padding:6px 12px;border-radius:12px;background:transparent;border:0;cursor:pointer;}
.nav-item.active{color:#fff;background:#23174f;}
.nav-item svg{width:22px;height:22px;fill:currentColor;}

/* App Detail Modal */
.detail-top{display:flex;align-items:center;gap:14px;margin-bottom:16px;}
.detail-icon{width:68px;height:68px;border-radius:18px;overflow:hidden;flex-shrink:0;background:#2a1f56;display:grid;place-items:center;}
.detail-icon img{width:100%;height:100%;object-fit:cover;}
.detail-info h2{margin:0 0 2px;font-size:18px;}
.detail-info p{margin:0 0 6px;color:var(--muted);font-size:13px;}
.badge{display:inline-block;padding:3px 8px;background:#271d4f;color:var(--purple);border-radius:8px;font-size:11px;font-weight:700;}
.stats-row{display:grid;grid-template-columns:repeat(3,1fr);text-align:center;background:#160f30;border:1px solid var(--border);border-radius:14px;padding:12px 6px;margin:16px 0;}
.stat-box .val{font-size:15px;font-weight:800;color:#fff;display:flex;align-items:center;justify-content:center;gap:3px;}
.stat-box .val span{color:var(--yellow);font-size:14px;}
.stat-box .lbl{font-size:11px;color:var(--muted);margin-top:2px;}
</style>
</head>
<body>

<header class="store-header">
  <div class="header-top">
    <div class="logo-brand">
      <button class="owner-avatar-btn" title="Owner Profile" onclick="document.getElementById('profileModal').classList.add('show')">
        {% if owner['avatar_filename'] %}
          <img src="{{ url_for('avatar_file', filename=owner['avatar_filename']) }}" alt="Owner">
        {% else %}
          <span>{{ owner['name'][0]|upper }}</span>
        {% endif %}
      </button>
      <div>
        <h1>{{ owner['name'] }} <span>Store</span></h1>
        <p>{{ apps|length }} Apps Available</p>
      </div>
    </div>
  </div>
  <div class="search-row">
    <input id="searchInput" type="search" placeholder="Search APKs..." oninput="filterCards()">
  </div>
</header>

<div class="content">
  {% with messages = get_flashed_messages() %}
    {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
  {% endwith %}

  <div class="section-title">
    <h2>
      {% if tab == 'top' %}Top Rated Apps
      {% elif tab == 'games' %}Games
      {% elif tab == 'books' %}Books & References
      {% else %}All Apps{% endif %}
    </h2>
  </div>

  {% if apps %}
  <div class="cards-grid" id="appsGrid">
    {% for a in apps %}
    <article class="card" data-name="{{ a['name']|lower }}" onclick="openAppDetail(
        '{{ a['id'] }}',
        '{{ a['name'] }}',
        '{{ a['category'] }}',
        '{{ a['rating'] }}',
        '{{ a['downloads'] }}',
        '{{ a['reviews_count'] }}',
        `{{ a['description'] | replace('`', '') }}`,
        '{{ url_for('icon', app_id=a['id']) if a['icon_filename'] else '' }}',
        '{{ url_for('download', app_id=a['id']) }}',
        '{{ format_size(a['file_size']) }}'
    )">
      <div class="thumb">
        {% if a['icon_filename'] %}
          <img src="{{ url_for('icon', app_id=a['id']) }}" alt="{{ a['name'] }}">
        {% else %}
          <div style="width:100%;height:100%;display:grid;place-items:center;font-size:26px;font-weight:900;
                      background:linear-gradient(135deg,var(--blue),var(--purple),var(--pink));color:#fff;">
            {{ a['name'][0]|upper }}
          </div>
        {% endif %}
      </div>
      <h3>{{ a['name'] }}</h3>
      <div class="rating">★ {{ a['rating'] }}</div>
    </article>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty-store">
    <div style="font-size:52px;">📲</div>
    <h2>No Items Found</h2>
    <p style="color:var(--muted)">Click the plus button below to add your first APK.</p>
  </div>
  {% endif %}
</div>

<!-- Floating Action Button for Upload -->
<button class="fab" title="Upload APK" onclick="document.getElementById('uploadModal').classList.add('show')">➕</button>

<!-- Bottom Navigation Bar -->
<nav class="bottom-nav">
  <a href="{{ url_for('index', tab='apps') }}" class="nav-item {{ 'active' if tab == 'apps' else '' }}">
    <svg viewBox="0 0 24 24"><path d="M4 4h7v7H4V4m9 0h7v7h-7V4M4 13h7v7H4v-7m9 0h7v7h-7v-7Z"/></svg>
    Apps
  </a>
  <a href="{{ url_for('index', tab='games') }}" class="nav-item {{ 'active' if tab == 'games' else '' }}">
    <svg viewBox="0 0 24 24"><path d="M21 6H3a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2m-10 3h2v2h2v2h-2v2h-2v-2H9v-2h2V9m3.5 7a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3m3-3a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3Z"/></svg>
    Games
  </a>
  <a href="{{ url_for('index', tab='top') }}" class="nav-item {{ 'active' if tab == 'top' else '' }}">
    <svg viewBox="0 0 24 24"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
    Top Apps
  </a>
  <a href="{{ url_for('index', tab='books') }}" class="nav-item {{ 'active' if tab == 'books' else '' }}">
    <svg viewBox="0 0 24 24"><path d="M18 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2M6 4h5v8l-2.5-1.5L6  12V4Z"/></svg>
    Books
  </a>
</nav>

<!-- App Detail Modal -->
<div class="modal" id="appDetailModal">
  <div class="modal-card">
    <div style="display:flex;justify-content:flex-end;margin-bottom:-10px;">
      <button onclick="document.getElementById('appDetailModal').classList.remove('show')" style="background:none;border:0;color:#fff;font-size:20px;cursor:pointer;">✕</button>
    </div>
    <div class="detail-top">
      <div class="detail-icon" id="modalIconContainer"></div>
      <div class="detail-info">
        <h2 id="modalAppName">App Name</h2>
        <p id="modalAppAuthor">Owner Store</p>
        <span class="badge" id="modalAppCategory">Tools</span>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-box">
        <div class="val"><span id="modalAppRating">5.0</span> ★</div>
        <div class="lbl" id="modalAppReviews">6 reviews</div>
      </div>
      <div class="stat-box">
        <div class="val" id="modalAppDownloads">200</div>
        <div class="lbl">Downloads</div>
      </div>
      <div class="stat-box">
        <div class="val" style="color:var(--green);justify-content:center;">🛡️</div>
        <div class="lbl">Verified</div>
      </div>
    </div>

    <div style="margin:16px 0;">
      <h3 style="font-size:14px;margin:0 0 6px;">About this app</h3>
      <p id="modalAppDesc" style="font-size:13px;color:var(--muted);margin:0;line-height:1.5;white-space:pre-wrap;"></p>
    </div>

    <div style="background:#160f30;border:1px solid var(--border);border-radius:14px;padding:12px;text-align:center;margin:16px 0;">
      <p style="font-size:12px;color:var(--muted);margin:0 0 8px;">Rate this app</p>
      <div style="color:var(--yellow);font-size:22px;letter-spacing:4px;">☆ ☆ ☆ ☆ ☆</div>
    </div>

    <div style="display:flex;gap:10px;margin-top:20px;">
      <a id="modalDownloadBtn" class="btn" style="flex:1;text-align:center;display:grid;place-items:center;" href="#">Download</a>
    </div>
  </div>
</div>

<!-- Owner Profile Modal -->
<div class="modal" id="profileModal">
  <div class="modal-card" style="text-align:center;">
    <h2>👑 Owner Profile</h2>
    <p style="color:var(--muted)">Only the owner can update this profile using the owner password.</p>
    <form method="post" action="{{ url_for('update_profile') }}" enctype="multipart/form-data">
      <div class="form-row">
        <label>Owner Name</label>
        <input name="owner_name" value="{{ owner['name'] }}" required>
      </div>
      <div class="form-row">
        <label>New Profile Picture</label>
        <input type="file" name="avatar_file" accept="image/*">
      </div>
      <div class="form-row">
        <label>🔐 Owner Password (Default is: naresh123)</label>
        <input type="password" name="owner_password" placeholder="Enter password to update profile" required>
      </div>
      <div class="modal-actions">
        <button type="button" class="cancel" onclick="document.getElementById('profileModal').classList.remove('show')">Close</button>
        <button class="btn" type="submit">💾 Save Profile</button>
      </div>
    </form>
  </div>
</div>

<!-- Upload Modal -->
<div class="modal" id="uploadModal">
  <div class="modal-card">
    <h2>🚀 Add New APK</h2>
    <p style="color:var(--muted)">Select your Android APK file and details to publish.</p>
    <form method="post" action="{{ url_for('upload') }}" enctype="multipart/form-data">
      <div class="form-row">
        <label>App Name</label>
        <input name="name" placeholder="e.g. Termux" required>
      </div>
      <div class="form-row">
        <label>Category</label>
        <select name="category">
          <option>Tools</option>
          <option>Games</option>
          <option>Productivity</option>
          <option>Social</option>
          <option>Books</option>
          <option>Utilities</option>
        </select>
      </div>
      <div class="form-row">
        <label>Select APK File (.apk only)</label>
        <input type="file" name="app_file" accept=".apk" required>
      </div>
      <div class="form-row">
        <label>Icon Image (optional)</label>
        <input type="file" name="icon_file" accept="image/*">
      </div>
      <div class="form-row">
        <label>Description (optional)</label>
        <textarea name="description" placeholder="App description..."></textarea>
      </div>
      <div class="modal-actions">
        <button type="button" class="cancel" onclick="document.getElementById('uploadModal').classList.remove('show')">Cancel</button>
        <button class="btn" type="submit">🚀 Publish APK</button>
      </div>
    </form>
  </div>
</div>

<script>
function filterCards(){
  const q = document.getElementById('searchInput').value.toLowerCase().trim();
  document.querySelectorAll('.card').forEach(card=>{
    card.style.display = (!q || card.dataset.name.includes(q)) ? '' : 'none';
  });
}

function openAppDetail(id, name, category, rating, downloads, reviews, desc, iconUrl, downloadUrl, fileSize){
  document.getElementById('modalAppName').innerText = name;
  document.getElementById('modalAppAuthor').innerText = "{{ owner['name'] }}";
  document.getElementById('modalAppCategory').innerText = category;
  document.getElementById('modalAppRating').innerText = rating;
  document.getElementById('modalAppDownloads').innerText = downloads + '+';
  document.getElementById('modalAppReviews').innerText = reviews + ' reviews';
  document.getElementById('modalAppDesc').innerText = desc;
  document.getElementById('modalDownloadBtn').href = downloadUrl;

  const iconContainer = document.getElementById('modalIconContainer');
  if(iconUrl){
    iconContainer.innerHTML = `<img src="${iconUrl}" alt="${name}">`;
  } else {
    iconContainer.innerHTML = `<div style="width:100%;height:100%;display:grid;place-items:center;font-size:28px;font-weight:900;background:linear-gradient(135deg,var(--blue),var(--purple),var(--pink));color:#fff;">${name[0].toUpperCase()}</div>`;
  }

  document.getElementById('appDetailModal').classList.add('show');
}

document.querySelectorAll('.modal').forEach(m=>{
  m.addEventListener('click', e=>{ if(e.target === m) m.classList.remove('show'); });
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
