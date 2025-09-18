# app.py
import os
from uuid import uuid4
from flask import Flask, render_template, request, url_for
from werkzeug.utils import secure_filename
from PIL import Image, ImageChops, ImageEnhance, ExifTags
import imagehash
import piexif

ALLOWED_EXT = {"png","jpg","jpeg","bmp"}
UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def save_file_storage(file_storage):
    filename = secure_filename(file_storage.filename)
    unique = f"{uuid4().hex}_{filename}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], unique)
    file_storage.save(path)
    return unique, path

def extract_metadata(path):
    try:
        exif_dict = piexif.load(path)
        meta = {}
        for ifd in exif_dict:
            for tag, val in exif_dict[ifd].items():
                name = piexif.TAGS[ifd].get(tag, {}).get("name", str(tag))
                meta[name] = str(val)
        return meta
    except Exception:
        # fallback to PIL._getexif
        try:
            img = Image.open(path)
            raw = img._getexif()
            if not raw:
                return {}
            meta = {}
            for tag, val in raw.items():
                name = ExifTags.TAGS.get(tag, tag)
                meta[name] = str(val)
            return meta
        except Exception:
            return {}

def generate_ela(path, out_name_prefix):
    try:
        img = Image.open(path).convert("RGB")
        temp = os.path.join(app.config["UPLOAD_FOLDER"], f"{out_name_prefix}_temp.jpg")
        img.save(temp, "JPEG", quality=90)
        comp = Image.open(temp)
        diff = ImageChops.difference(img, comp)
        diff = ImageEnhance.Brightness(diff).enhance(30.0)
        ela_name = f"{out_name_prefix}_ela.png"
        ela_path = os.path.join(app.config["UPLOAD_FOLDER"], ela_name)
        diff.save(ela_path)
        os.remove(temp)
        return ela_name
    except Exception as e:
        print("ELA error:", e)
        return None

def compare_phash(path1, path2):
    try:
        h1 = imagehash.phash(Image.open(path1))
        h2 = imagehash.phash(Image.open(path2))
        return str(h1), str(h2), int(h1 - h2)
    except Exception as e:
        return None, None, f"Error: {e}"

@app.route("/", methods=["GET","POST"])
def index():
    context = {}
    if request.method == "POST":
        f1 = request.files.get("original")
        f2 = request.files.get("sospechosa")
        if not f1 or not f2 or not allowed_file(f1.filename) or not allowed_file(f2.filename):
            context["error"] = "Carga dos imágenes válidas (jpg/png...)"
            return render_template("index.html", **context)

        name1, path1 = save_file_storage(f1)
        name2, path2 = save_file_storage(f2)

        meta1 = extract_metadata(path1)
        meta2 = extract_metadata(path2)

        h1, h2, diff = compare_phash(path1, path2)

        out_prefix = uuid4().hex
        ela_name = generate_ela(path2, out_prefix)
        ela_url = url_for('static', filename=f"uploads/{ela_name}") if ela_name else None

        context.update({
            "meta1": meta1, "meta2": meta2,
            "hash1": h1, "hash2": h2, "hashdiff": diff,
            "ela_url": ela_url,
            "img1_url": url_for('static', filename=f"uploads/{name1}"),
            "img2_url": url_for('static', filename=f"uploads/{name2}")
        })

    return render_template("index.html", **context)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
