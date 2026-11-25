import os
import re
import sqlite3
import secrets
import base64
import io
import json
from datetime import datetime, timezone
from functools import wraps
import numpy as np
from PIL import Image, ImageStat, ImageFilter, UnidentifiedImageError
from flask import Flask, request, jsonify, render_template, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "loomcycle.db")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-this-secret"),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_PIXELS = 25_000_000


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT NOT NULL,
            dominant_colour TEXT NOT NULL,
            brightness REAL NOT NULL,
            contrast REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            filename TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS sustainability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            material_kg REAL NOT NULL,
            pieces INTEGER NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """)
        # Safe, additive migration for existing databases. Existing records are retained.
        analysis_columns = {row[1] for row in conn.execute("PRAGMA table_info(analyses)").fetchall()}
        if "fabric_ai_json" not in analysis_columns:
            conn.execute("ALTER TABLE analyses ADD COLUMN fabric_ai_json TEXT")
    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    except Exception:
        pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with db() as conn:
        row = conn.execute("SELECT id, name, email FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "Please log in to continue."}), 401
        return fn(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        raise ValueError("Choose an image first.")
    safe_name = secure_filename(file_storage.filename)
    if not allowed_file(safe_name):
        raise ValueError("Use a PNG, JPG, JPEG or WEBP image.")
    unique_name = f"{secrets.token_hex(12)}_{safe_name}"
    path = os.path.join(UPLOAD_DIR, unique_name)
    try:
        file_storage.save(path)
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            if im.width * im.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions are too large.")
    except (UnidentifiedImageError, OSError):
        if os.path.exists(path):
            os.remove(path)
        raise ValueError("The uploaded file is not a valid image.")
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return unique_name


def inspect_image(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    with Image.open(path) as original:
        image = original.convert("RGB").resize((160, 160))
    stat = ImageStat.Stat(image)
    brightness = float(sum(stat.mean) / 3)
    contrast = float(sum(stat.stddev) / 3)
    small = np.asarray(image, dtype=np.uint8)
    pixels = small.reshape(-1, 3)
    avg = np.mean(pixels, axis=0).astype(int)
    colour = "#{:02X}{:02X}{:02X}".format(*avg.tolist())
    edge_image = image.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_strength = float(ImageStat.Stat(edge_image).mean[0])
    return {
        "dominant_colour": colour,
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
        "texture_score": round(edge_strength, 1),
    }


def analyze_fabric_with_ai(filename):
    """Return a cautious visual textile estimate using an image-capable OpenAI model.

    This is image-based inference, not a laboratory fibre test. The API key remains
    server-side; the image is sent to the configured API only when this function runs.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.lower() == "your_api_key_here":
        return None

    from openai import OpenAI

    image_path = os.path.join(UPLOAD_DIR, filename)
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        image.thumbnail((1200, 1200))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    image_data_url = f"data:image/jpeg;base64,{encoded}"

    client = OpenAI(api_key=api_key, timeout=45.0, max_retries=1)
    model = os.environ.get("OPENAI_VISION_MODEL", os.environ.get("OPENAI_MODEL", "gpt-5.5")).strip()
    prompt = """Examine this close-up textile photo for a student textile upcycling project.
Give a cautious VISUAL estimate only. Do not claim a photograph can prove fibre content.
If the image is not clearly fabric or is too unclear, say unknown and use low confidence.
Distinguish visible fabric construction (woven/knit/nonwoven/unclear) from probable fibre.
A single still photo cannot reliably test stretch, weight, fibre percentages, or exact blend.
Return ONLY valid JSON with these keys:
{
  "probable_fabric_type": "short label such as denim/twill-like, plain-woven cotton-like, knit, satin-like, wool-like, synthetic-looking, blended/uncertain, or unknown",
  "likely_fibre": "carefully worded likely fibre or unknown",
  "confidence": "low, moderate, or high",
  "confidence_reason": "one short sentence explaining visual evidence and uncertainty",
  "construction": "woven, knitted, nonwoven, or unclear",
  "visible_features": ["2-5 concise observable features"],
  "condition": "brief visible condition note, or cannot assess",
  "project_recommendations": [
    {"title":"project name", "detail":"why this might suit the visible fabric; do not assume unobserved strength", "level":"Easy/Medium/Advanced"}
  ],
  "limitations": "one short caveat about photo-based identification"
}
Provide 2-3 project recommendations. Do not invent exact fibre percentages or certifications."""
    response = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_data_url, "detail": "high"},
            ],
        }],
        text={"format": {"type": "json_object"}},
        max_output_tokens=700,
    )
    raw = (response.output_text or "").strip()
    if not raw:
        raise RuntimeError("The vision model returned an empty response.")
    # Be tolerant of a model wrapping JSON in a markdown code fence.
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The vision model did not return valid structured text.") from exc

    allowed_confidence = {"low", "moderate", "high"}
    confidence = str(result.get("confidence", "low")).lower()
    result["confidence"] = confidence if confidence in allowed_confidence else "low"
    for key in ("probable_fabric_type", "likely_fibre", "confidence_reason", "construction", "condition", "limitations"):
        result[key] = str(result.get(key, "Not clear from this image."))[:500]
    for key in ("visible_features", "project_recommendations"):
        if not isinstance(result.get(key), list):
            result[key] = []
        result[key] = result[key][:5]
    cleaned_recommendations = []
    for item in result["project_recommendations"]:
        if not isinstance(item, dict):
            continue
        cleaned_recommendations.append({
            "title": str(item.get("title", "Textile reuse idea"))[:100],
            "detail": str(item.get("detail", "Consider this as a possible reuse."))[:350],
            "level": str(item.get("level", "Beginner"))[:30],
        })
    result["project_recommendations"] = cleaned_recommendations
    result["visible_features"] = [str(x)[:150] for x in result["visible_features"]]
    return result


def make_recommendations(analysis):
    brightness = analysis["brightness"]
    contrast = analysis["contrast"]
    suggestions = []
    if brightness < 105:
        suggestions.append({"title": "Bright contrast patchwork", "detail": "Pair this darker fabric with cream, natural cotton or a lighter scrap to create contrast.", "level": "Easy"})
    elif brightness > 185:
        suggestions.append({"title": "Layered textured collage", "detail": "Combine the light fabric with darker denim or earthy scraps for depth.", "level": "Easy"})
    else:
        suggestions.append({"title": "Reusable fabric tote", "detail": "This mid-tone fabric can work well as a panel for a small tote or pouch.", "level": "Medium"})
    if contrast > 55:
        suggestions.append({"title": "Visible mending artwork", "detail": "Use the fabric's texture as a feature and add simple running-stitch details.", "level": "Easy"})
    else:
        suggestions.append({"title": "Appliqué composition", "detail": "Layer shapes cut from contrasting textile scraps to create a decorative panel.", "level": "Medium"})
    suggestions.append({"title": "Patchwork notebook cover", "detail": "Cut reusable pieces into geometric shapes and stitch or fabric-glue them onto a cover.", "level": "Easy"})
    return suggestions


TUTORIALS = [
    {"id": 1, "title": "No-sew fabric coaster", "category": "Home", "level": "Beginner", "time": "20 min", "steps": ["Cut two equal fabric squares.", "Place a thin recycled-cardboard layer between them.", "Fold the edges inward and secure with fabric glue.", "Press flat and let it dry fully."]},
    {"id": 2, "title": "Patchwork tote panel", "category": "Accessories", "level": "Intermediate", "time": "60 min", "steps": ["Choose sturdy fabric scraps.", "Arrange pieces into a balanced panel.", "Pin and stitch the pieces together.", "Attach the panel to a reusable tote body."]},
    {"id": 3, "title": "Visible mending", "category": "Repair", "level": "Beginner", "time": "30 min", "steps": ["Trim loose threads around the damaged area.", "Place a contrasting scrap behind the hole.", "Use running stitches to secure the patch.", "Add decorative stitches if desired."]},
    {"id": 4, "title": "Braided textile basket", "category": "Home", "level": "Intermediate", "time": "75 min", "steps": ["Cut old fabric into long strips.", "Tie strips together into continuous lengths.", "Braid three strips tightly.", "Coil the braid and stitch each row in place."]},
]


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "LOOMCYCLE AI"})


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or request.form
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(name) < 2 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({"error": "Enter a valid name and email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must contain at least 8 characters."}), 400
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                (name, email, generate_password_hash(password), now())
            )
            session["user_id"] = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with this email already exists."}), 409
    return jsonify({"message": "Account created successfully.", "user": current_user()}), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or request.form
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401
    session.clear()
    session["user_id"] = user["id"]
    return jsonify({"message": "Welcome back.", "user": current_user()})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"message": "You have been logged out."})


@app.get("/api/me")
def me():
    user = current_user()
    return jsonify({"user": user})


@app.post("/api/analyze")
def analyze():
    uploaded = request.files.get("image")
    try:
        filename = save_image(uploaded)
        result = inspect_image(filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    ai_analysis = None
    ai_status = "not_configured"
    ai_notice = "AI fabric identification is not configured. Basic colour and image metrics are available, but they do not identify fibre type."
    try:
        ai_analysis = analyze_fabric_with_ai(filename)
        if ai_analysis is not None:
            ai_status = "success"
            ai_notice = "AI visual estimate only. A fabric label or laboratory test is needed to verify fibre composition."
    except Exception as exc:
        app.logger.warning("Fabric vision analysis failed (%s): %s", type(exc).__name__, str(exc)[:500])
        ai_status = "error"
        ai_notice = "The AI vision request failed. No fabric type was confirmed; the basic image measurements below are not fibre identification. Check the API key, model setting, internet connection and API account."

    user = current_user()
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO analyses(user_id,filename,dominant_colour,brightness,contrast,created_at,fabric_ai_json)
               VALUES(?,?,?,?,?,?,?)""",
            (user["id"] if user else None, filename, result["dominant_colour"],
             result["brightness"], result["contrast"], now(),
             json.dumps(ai_analysis, ensure_ascii=False) if ai_analysis else None)
        )
        result["analysis_id"] = cur.lastrowid
    result["image_url"] = f"/uploads/{filename}"
    result["fabric_ai"] = ai_analysis
    result["ai_status"] = ai_status
    result["ai_notice"] = ai_notice
    result["recommendations"] = (ai_analysis or {}).get("project_recommendations") or make_recommendations(result)
    result["notice"] = "Basic image metrics describe colour, brightness, contrast and edges only. They cannot identify fibre composition."
    return jsonify(result)


@app.post("/api/recommendations")
def recommendations():
    data = request.get_json(silent=True) or {}
    try:
        analysis = {
            "brightness": float(data.get("brightness", 130)),
            "contrast": float(data.get("contrast", 40)),
        }
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid analysis values."}), 400
    return jsonify({"recommendations": make_recommendations(analysis)})


@app.get("/api/tutorials")
def tutorials():
    return jsonify({"tutorials": TUTORIALS})


@app.post("/api/artwork/prompt")
def artwork_prompt():
    data = request.get_json(silent=True) or {}
    material = str(data.get("material", "recycled fabric")).strip()[:80]
    style = str(data.get("style", "modern minimal")).strip()[:80]
    purpose = str(data.get("purpose", "wall art")).strip()[:80]
    prompt = (
        f"Create a sustainable {purpose} concept using {material}. "
        f"Style: {style}. Use visible textile layers, reclaimed fabric textures, "
        "thoughtful colour blocking, hand-crafted details and a low-waste composition."
    )
    return jsonify({"prompt": prompt, "notice": "This endpoint creates a text concept prompt; it does not generate an image."})


@app.get("/api/gallery")
def gallery():
    with db() as conn:
        rows = conn.execute("""
            SELECT g.id,g.title,g.description,g.filename,g.created_at,u.name AS creator
            FROM gallery g LEFT JOIN users u ON g.user_id=u.id
            ORDER BY g.id DESC LIMIT 60
        """).fetchall()
    return jsonify({"items": [
        {"id": r["id"], "title": r["title"], "description": r["description"],
         "image_url": f"/uploads/{r['filename']}", "created_at": r["created_at"],
         "creator": r["creator"] or "Community member"} for r in rows
    ]})


@app.post("/api/gallery")
@login_required
def add_gallery():
    data = request.form
    title = str(data.get("title", "")).strip()[:100]
    description = str(data.get("description", "")).strip()[:500]
    if not title:
        return jsonify({"error": "Add a title for your artwork."}), 400
    try:
        filename = save_image(request.files.get("image"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    user = current_user()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO gallery(user_id,title,description,filename,created_at) VALUES(?,?,?,?,?)",
            (user["id"], title, description, filename, now())
        )
    return jsonify({"message": "Artwork added to the community gallery.", "id": cur.lastrowid}), 201


@app.post("/api/sustainability")
@login_required
def save_sustainability():
    data = request.get_json(silent=True) or {}
    try:
        kg = float(data.get("material_kg", 0))
        pieces = int(data.get("pieces", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Enter valid numbers."}), 400
    if not (0 < kg <= 10000) or not (0 <= pieces <= 100000):
        return jsonify({"error": "Enter a positive material weight and a reasonable piece count."}), 400
    note = str(data.get("note", "")).strip()[:250]
    user = current_user()
    with db() as conn:
        conn.execute(
            "INSERT INTO sustainability(user_id,material_kg,pieces,note,created_at) VALUES(?,?,?,?,?)",
            (user["id"], kg, pieces, note, now())
        )
    return jsonify({"message": "Reuse record saved."}), 201


@app.get("/api/sustainability/history")
@login_required
def sustainability_history():
    user = current_user()
    with db() as conn:
        rows = conn.execute(
            "SELECT material_kg,pieces,note,created_at FROM sustainability WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (user["id"],)
        ).fetchall()
        totals = conn.execute(
            "SELECT COALESCE(SUM(material_kg),0) AS kg, COALESCE(SUM(pieces),0) AS pieces FROM sustainability WHERE user_id=?",
            (user["id"],)
        ).fetchone()
    return jsonify({
        "total_kg": round(totals["kg"], 3), "total_pieces": totals["pieces"],
        "history": [dict(r) for r in rows],
        "notice": "These figures record material reuse only; they do not estimate carbon or water savings."
    })


@app.get("/api/dashboard")
@login_required
def dashboard():
    user = current_user()
    with db() as conn:
        analyses = conn.execute("SELECT COUNT(*) FROM analyses WHERE user_id=?", (user["id"],)).fetchone()[0]
        gallery_count = conn.execute("SELECT COUNT(*) FROM gallery WHERE user_id=?", (user["id"],)).fetchone()[0]
        totals = conn.execute("SELECT COALESCE(SUM(material_kg),0),COALESCE(SUM(pieces),0) FROM sustainability WHERE user_id=?", (user["id"],)).fetchone()
    return jsonify({"analyses": analyses, "gallery_posts": gallery_count, "reused_kg": round(totals[0], 3), "reused_pieces": totals[1]})


def local_loom_bot_answer(question):
    """Useful offline textile-reuse guidance when no AI API key is configured."""
    q = question.lower()
    if any(w in q for w in ["denim", "jeans"]):
        return ("Denim is sturdy and works well for a tote, pouch, patchwork cushion or visible-mending patch.\n\n"
                "Try this: 1) inspect and wash the fabric, 2) cut around worn areas, 3) plan matching panels, "
                "4) use a strong needle and reinforce handles, corners and seams. Save small strips for braided details.")
    if any(w in q for w in ["cotton", "shirt", "kurta"]):
        return ("Cotton garments and loom offcuts can become a pouch, pillow cover, produce bag, coaster or patchwork panel.\n\n"
                "Choose a project based on the largest usable piece, keep seams aligned with the fabric grain where possible, "
                "and reserve tiny scraps for stuffing or appliqué if clean and suitable.")
    if any(w in q for w in ["wool", "knit", "sweater"]):
        return ("Knit and wool pieces are useful for soft coasters, appliqué, patching knitwear and small pouches.\n\n"
                "Use a gentle wash suited to the care label, avoid high heat, and stabilize stretchy edges before sewing.")
    if any(w in q for w in ["pillow", "cushion"]):
        return ("For a patchwork pillow cover, start with medium-to-large scraps. 1) Sort by colour and weight, "
                "2) arrange a balanced layout, 3) stitch panels into a front square, 4) add a backing and envelope or zip closure.\n\n"
                "Use similar fabric weights so the cover lies flat.")
    if any(w in q for w in ["bag", "tote", "pouch"]):
        return ("For a bag or pouch, choose the strongest fabric pieces for the body and straps. "
                "Add a lining if the fabric is thin, use interfacing or a second layer for structure, "
                "and reinforce stress points with backstitching.\n\n"
                "A small pouch is a good first project; a tote needs stronger seams and handles.")
    if any(w in q for w in ["repair", "hole", "tear", "mend", "damaged"]):
        return ("For a repair, trim only loose threads, place a compatible patch behind or over the damaged area, "
                "and secure it with running stitch, whip stitch or a machine seam.\n\n"
                "Keep the patch larger than the hole and reinforce the surrounding fabric, not just the damaged edge.")
    if any(w in q for w in ["wash", "clean", "smell", "stain"]):
        return ("Check the care label and identify the fibre if possible. Separate colours, test any cleaner on a hidden spot, "
                "wash gently and dry completely before storing or crafting.\n\n"
                "Do not mix cleaning chemicals. If fabric is mouldy or contaminated, handle it carefully and do not use it for items that touch skin or food.")
    if any(w in q for w in ["sort", "recycle", "waste", "leftover", "scrap"]):
        return ("Sort textile waste into: reusable garment-sized pieces, medium offcuts, narrow strips and tiny scraps. "
                "Repair wearable pieces first; use medium scraps for patchwork, strips for braiding, and clean tiny scraps for stuffing or craft details.\n\n"
                "Keep unknown or mixed-fibre pieces separate until you know how they can be reused or recycled.")
    return ("Start with the fabric you have: note its fibre (if known), thickness, stretch, size and condition. "
            "Choose a project that matches the largest usable piece, repair anything still wearable, and keep scraps sorted by size.\n\n"
            "Tell me the fabric type, approximate piece size and what you want to make, and I can suggest a more specific plan.")


@app.post("/api/loom-bot")
def loom_bot():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Type a question first."}), 400
    if len(question) > 1200:
        return jsonify({"error": "Please keep your question under 1,200 characters."}), 400

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, timeout=25.0, max_retries=1)
            response = client.responses.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-5.5"),
                instructions=(
                    "You are Loom Bot, a practical textile reuse and upcycling assistant for a student sustainability project. "
                    "Answer in clear, friendly steps. Help with fabric identification caveats, project selection, sewing, "
                    "repair, cleaning, product design and waste sorting. Ask one concise follow-up when key details are missing. "
                    "Prioritize reuse and repair, avoid unsupported environmental savings claims, and give sensible safety advice. "
                    "Do not claim to inspect an image unless one was provided in this request."
                ),
                input=question,
                max_output_tokens=500,
            )
            answer = (response.output_text or "").strip()
            if answer:
                return jsonify({"answer": answer, "mode": "ai", "notice": "AI-generated guidance. Check material care labels and use safe crafting practices."})
        except Exception as exc:
            app.logger.warning("Loom Bot AI request failed (%s)", type(exc).__name__)
            return jsonify({"answer": local_loom_bot_answer(question), "mode": "local", "notice": "AI service could not be reached, so Loom Bot used its built-in textile guidance."})

    return jsonify({
        "answer": local_loom_bot_answer(question),
        "mode": "local",
        "notice": "Textile knowledge mode. Add an OPENAI_API_KEY on the Flask server to enable generative AI responses. API usage may incur separate charges."
    })


@app.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "File is too large. Maximum upload size is 8 MB."}), 413


@app.errorhandler(500)
def server_error(error):
    app.logger.error("Internal server error: %s", error)
    return jsonify({"error": "An internal server error occurred."}), 500


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
