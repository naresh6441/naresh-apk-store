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

# Vercel serverless environment check (Vercel uses /tmp for writable storage)
IS_VERCEL = os.environ.get("VERCEL") == "1"
if IS_VERCEL:
    BASE_DIR = "/tmp"
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "store.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_APP_EXTENSIONS = {"apk"}
ALLOWED_ICON_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("USE_HTTPS") == "1",
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
            created_at TEXT NOT NULL
        )
    """)
    # Owner Profile Table (Stores Owner Profile Image & Secure Password)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS owner_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL,
            avatar_filename TEXT,
            password_hash TEXT
        )
    """)
    
    # Default owner profile creation if not exists
    existing = conn.execute("SELECT id FROM owner_profile WHERE id = 1").fetchone()
    if not existing:
        default_pwd = generate_password_hash("naresh123")  # Default owner password
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


def get_apps(order_by_rating=False):
    conn = get_db()
    sql = "SELECT * FROM apps ORDER BY " + (
        "rating DESC" if order_by_rating else "created_at DESC"
    )
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
    apps_rows = get_apps(order_by_rating=(tab == "top"))
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
    app_file.save(os.path.join(UPLOAD_DIR, file_filename))
    file_size = os.path.getsize(os.path.join(UPLOAD_DIR, file_filename))

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
    return redirect(url_for("index"))


@app.route("/profile/update", methods=["POST"])
def update_profile():
    password = request.form.get("owner_password", "")
    new_name = request.form.get("owner_name", "Naresh XX").strip()
    avatar_file = request.files.get("avatar_file")

    owner = get_owner()
    # Check owner password to secure profile changes
    if not check_password_hash(owner["password_hash"], password):
        flash("❌ Wrong Owner Password! Profile cannot be changed.")
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
  margin:0;font-family:Inter,system-ui,sans-serif;color:var(--text);padding-bottom:40px;
  background:radial-gradient(circle at 10% 10%,#1e3fae66,transparent 25%),
             radial-gradient(circle at 90% 20%,#8a1fc966,transparent 25%),
             radial-gradient(circle at 50% 100%,#ff2d9233,transparent 30%),var(--bg);
}
a{color:inherit}
.store-header{position:sticky;top:0;z-index:50;background:linear-gradient(180deg,#1a1338,#150f2e 90%);
  border-bottom:1px solid var(--border);padding:16px 18px;}
.header-top{display:flex;align-items:center;justify-content:space-between;gap:12px;}
.logo-brand{display:flex;align-items:center;gap:12px;}
.owner-avatar-btn{width:52px;height:52px;border-radius:16px;border:2px solid var(--blue);overflow:hidden;cursor:pointer;
  background:linear-gradient(135deg,var(--blue),var(--purple),var(--pink));display:grid;place-items:center;padding:0;}
.owner-avatar-btn img{width:100%;height:100%;object-fit:cover;}
.owner-avatar-btn span{font-size:22px;font-weight:900;color:#fff;}
.logo-brand h1{font-size:19px;margin:0;}
.logo-brand h1 span{background:linear-gradient(90deg,var(--blue),var(--purple),var(--pink));
  -webkit-background-clip:text;color:transparent;}
.logo-brand p{margin:2px 0 0;color:var(--muted);font-size:13px;}
.search-row{margin-top:14px;}
.search-row input{width:100%;height:44px;border:1px solid var(--border);background:#160f30;color:#fff;
  border-radius:12px;padding:0 15px;outline:0;}
.content{padding:20px 16px 10px;max-width:1100px;margin:0 auto;}
.section-title{display:flex;align-items:center;gap:8px;margin:6px 0 16px;}
.tabs{display:flex;gap:10px;margin-bottom:16px;}
.tabs a{padding:8px 14px;border-radius:10px;border:1px solid var(--border);color:var(--muted);font-size:13px;text-decoration:none;}
.tabs a.active{color:#fff;border-color:var(--blue);background:#1e1642;}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:10px;}
.card{background:linear-gradient(145deg,#20134a,#15102f 55%,#241044);border:1px solid #5d43a8;
  border-radius:13px;padding:8px 6px;text-align:center;}
.thumb{width:72%;aspect-ratio:1/1;margin:0 auto 7px;border-radius:18px;overflow:hidden;display:grid;
  place-items:center;font-size:30px;background:radial-gradient(circle,#3a2f6b,#150f2e);}
.thumb img{width:100%;height:100%;object-fit:cover;}
.card h3{font-size:11px;margin:0 0 3px;min-height:28px;}
.card .rating{font-size:10px;color:var(--yellow);}
.card .filesize{font-size:9px;color:var(--muted);margin-top:2px;}
.card-actions{display:flex;gap:4px;margin-top:6px;}
.small-btn{flex:1;padding:6px 4px;border-radius:7px;border:1px solid #4a3b7a;background:#1a1338;
  color:#fff;font-size:10px;font-weight:800;cursor:pointer;text-decoration:none;display:inline-block;}
.install{background:linear-gradient(135deg,#00d4ff,#7c4dff 52%,#ff2d92);border-color:transparent;box-shadow:0 4px 12px #8a2be644;}
.empty-store{margin-top:20px;padding:55px 20px;text-align:center;border:1px dashed #4a3b7a;
  border-radius:18px;background:linear-gradient(145deg,#160f30,#1c1030);}
.btn{border:0;border-radius:11px;padding:12px 20px;background:linear-gradient(90deg,var(--blue),var(--purple),var(--pink));
  color:#fff;font-weight:800;cursor:pointer;}
.cancel{border:1px solid #4a3b7a;background:transparent;color:#dbe4f2;border-radius:10px;padding:11px 17px;cursor:pointer;}
.modal{position:fixed;inset:0;background:#000c;display:none;place-items:center;z-index:300;padding:20px;}
.modal.show{display:grid;}
.modal-card{width:min(520px,100%);max-height:90vh;overflow:auto;background:linear-gradient(145deg,#1c1440,#120b2c);
  border:1px solid #4a3b7a;border-radius:20px;padding:22px;}
.form-row{display:grid;gap:7px;margin:13px 0;}
.form-row label{font-size:13px;color:#c9bfe8;}
.form-row input,.form-row textarea,.form-row select{width:100%;border:1px solid #4a3b7a;background:#160f30;
  color:#fff;border-radius:10px;padding:11px;outline:none;}
.form-row textarea{min-height:80px;}
.modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:16px;flex-wrap:wrap;}
.flash{background:#1e1642;border:1px solid var(--blue);border-radius:10px;padding:12px 16px;margin:14px 0;font-size:14px;}
.fab{position:fixed;right:20px;bottom:20px;border-radius:50%;width:56px;height:56px;font-size:22px;
  background:linear-gradient(90deg,var(--blue),var(--purple));border:0;color:#fff;box-shadow:0 8px 22px #a855f755;cursor:pointer;}
</style>
</head>
<body>

<header class="store-header">
  <div class="header-top">
    <div class="logo-brand">
      <!-- Owner Profile Picture Button (Clicking opens profile modal) -->
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

  <div class="tabs">
    <a href="{{ url_for('index', tab='apps') }}" class="{{ 'active' if tab != 'top' else '' }}">▦ All APKs</a>
    <a href="{{ url_for('index', tab='top') }}" class="{{ 'active' if tab == 'top' else '' }}">🏆 Top Rated</a>
  </div>

  <div class="section-title"><h2>{{ 'Top Rated APKs' if tab == 'top' else 'All APK Files' }}</h2></div>

  {% if apps %}
  <div class="cards-grid" id="appsGrid">
    {% for a in apps %}
    <article class="card" data-name="{{ a['name']|lower }}">
      <div class="thumb">
        {% if a['icon_filename'] %}
          <img src="{{ url_for('icon', app_id=a['id']) }}" alt="{{ a['name'] }} icon">
        {% else %}
          <div style="width:100%;height:100%;display:grid;place-items:center;font-size:34px;font-weight:900;
                      background:linear-gradient(135deg,var(--blue),var(--purple),var(--pink));color:#fff;">
            {{ a['name'][0]|upper }}
          </div>
        {% endif %}
      </div>
      <h3>{{ a['name'] }}</h3>
      <div class="rating">★ {{ a['rating'] }}</div>
      <div class="filesize">{{ format_size(a['file_size']) }}</div>
      <div class="card-actions">
        <a class="small-btn install" href="{{ url_for('download', app_id=a['id']) }}">Download</a>
      </div>
    </article>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty-store">
    <div style="font-size:56px;">📲</div>
    <h2>No APKs Uploaded Yet</h2>
    <p style="color:var(--muted)">Click below to add your first Android APK.</p>
    <button class="btn" style="margin-top:14px;" onclick="document.getElementById('uploadModal').classList.add('show')">
      🚀 Add APK File
    </button>
  </div>
  {% endif %}
</div>

<!-- Floating Action Button -->
<button class="fab" title="Upload APK" onclick="document.getElementById('uploadModal').classList.add('show')">➕</button>

<!-- Owner Profile Modal (Protected by Owner Password so visitors cannot change it) -->
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
        <label>🔐 Owner Password (Default: naresh123)</label>
        <input type="password" name="owner_password" placeholder="Enter owner password" required>
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
        <input name="name" placeholder="e.g. My Android App" required>
      </div>
      <div class="form-row">
        <label>Category</label>
        <select name="category">
          <option>Games</option>
          <option>Tools</option>
          <option>Productivity</option>
          <option>Social</option>
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
