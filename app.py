# app.py
import os
from uuid import uuid4
from datetime import datetime
from flask import Flask, render_template, request, url_for
from werkzeug.utils import secure_filename
from PIL import Image, ImageChops, ImageEnhance, ExifTags
import imagehash
import piexif

ALLOWED_EXT = {"png", "jpg", "jpeg", "bmp"}
UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
# Para evitar errores de límite de tamaño, puedes comentar la siguiente línea
# app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# ----------------------- Funciones -----------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def save_file_storage(file_storage):
    filename = secure_filename(file_storage.filename)
    unique = f"{uuid4().hex}_{filename}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], unique)
    file_storage.save(path)
    return unique, path

def extract_metadata(path):
    meta = {}
    try:
        exif_dict = piexif.load(path)
        for ifd in exif_dict:
            for tag, val in exif_dict[ifd].items():
                name = piexif.TAGS[ifd].get(tag, {}).get("name", str(tag))
                meta[name] = val.decode() if isinstance(val, bytes) else str(val)
        if meta:
            return meta
    except Exception:
        pass

    try:
        img = Image.open(path)
        raw = img._getexif()
        if raw:
            for tag, val in raw.items():
                name = ExifTags.TAGS.get(tag, tag)
                meta[name] = str(val)
        if meta:
            return meta
        # Si no hay EXIF, añadimos info básica de la imagen
        meta["Format"] = img.format
        meta["Mode"] = img.mode
        meta["Size"] = f"{img.width}x{img.height}"
        return meta
    except Exception:
        try:
            img = Image.open(path)
            return {"Format": img.format, "Mode": img.mode, "Size": f"{img.width}x{img.height}"}
        except Exception:
            return {}

def get_metadata_safe(path):
    meta = extract_metadata(path)
    data = {}
    data["Model"] = meta.get("Model") or meta.get("CameraModelName") or "desconocido"
    data["DateCreated"] = meta.get("DateTimeOriginal") or meta.get("DateTime") or "desconocida"
    exif_mod = meta.get("ModifyDate") or meta.get("DateTimeDigitized")
    if exif_mod:
        data["DateModified"] = exif_mod
    else:
        ts = os.path.getmtime(path)
        data["DateModified"] = datetime.fromtimestamp(ts).strftime("%Y:%m:%d %H:%M:%S")
    data["Software"] = meta.get("Software", "desconocido")
    data["all_metadata"] = meta
    return data

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

def compare_ela(path1, path2):
    try:
        img1 = Image.open(path1).convert("L")
        img2 = Image.open(path2).convert("L")
        diff = ImageChops.difference(img1, img2)
        total_pixels = diff.size[0] * diff.size[1]
        nonzero = sum(1 for v in diff.getdata() if v != 0)
        percent = (nonzero / total_pixels) * 100
        return round(percent, 2)
    except Exception:
        return None

# ----------------------- Rutas -----------------------
@app.route("/", methods=["GET","POST"])
def index():
    context = {"current_year": datetime.now().year}
    if request.method == "POST":
        f1 = request.files.get("original")
        f2 = request.files.get("sospechosa")
        if not f1 or not f2 or not allowed_file(f1.filename) or not allowed_file(f2.filename):
            context["error"] = "Carga dos imágenes válidas (jpg/png...)"
            return render_template("index.html", **context)

        name1, path1 = save_file_storage(f1)
        name2, path2 = save_file_storage(f2)

        meta1 = get_metadata_safe(path1)
        meta2 = get_metadata_safe(path2)

        h1, h2, diff = compare_phash(path1, path2)

        out_prefix1 = uuid4().hex
        out_prefix2 = uuid4().hex
        ela_name1 = generate_ela(path1, out_prefix1)
        ela_name2 = generate_ela(path2, out_prefix2)
        ela_url1 = url_for('static', filename=f"uploads/{ela_name1}") if ela_name1 else None
        ela_url2 = url_for('static', filename=f"uploads/{ela_name2}") if ela_name2 else None

        informe = []
        informe.append("Informe de Casos de Prueba:")
        informe.append(f"Caso 1: Imagen original '{f1.filename}'")
        informe.append(f"  - Modelo cámara: {meta1['Model']}")
        informe.append(f"  - Fecha de captura: {meta1['DateCreated']}")
        informe.append(f"  - Fecha de modificación: {meta1['DateModified']}")
        informe.append(f"  - Hash perceptual: referencia")
        informe.append(f"  - ELA: referencia")
        informe.append(f"Caso 2: Imagen sospechosa '{f2.filename}'")
        software_detected = meta2['Software'] if meta2['Software'] != "desconocido" else "Software no detectado"
        informe.append(f"  - Software: {software_detected}")
        informe.append(f"  - Fecha de captura: {meta2['DateCreated']}")
        informe.append(f"  - Fecha de modificación: {meta2['DateModified']}")
        informe.append(f"  - Hash perceptual: Diferencia = {diff}")

        ela_diff_percent = None
        if ela_name1 and ela_name2:
            ela_diff_percent = compare_ela(
                os.path.join(app.config["UPLOAD_FOLDER"], ela_name1),
                os.path.join(app.config["UPLOAD_FOLDER"], ela_name2)
            )
            informe.append(f"  - ELA comparativa: {ela_diff_percent}% píxeles diferentes")

        editada = False
        if isinstance(diff, int) and diff > 10:
            editada = True
        if ela_diff_percent and ela_diff_percent > 2:
            editada = True
        informe.append(f"  - Estado: {'Editada / Posible manipulación' if editada else 'Importante: Sin indicios de edición'}")

        context.update({
            "meta1": meta1,
            "meta2": meta2,
            "hash1": h1,
            "hash2": h2,
            "hashdiff": diff,
            "ela_url1": ela_url1,
            "ela_url2": ela_url2,
            "informe": "\n".join(informe),
            "img1_url": url_for('static', filename=f"uploads/{name1}"),
            "img2_url": url_for('static', filename=f"uploads/{name2}")
        })

    return render_template("index.html", **context)

# ----------------------- Run -----------------------
# No usar app.run en Render; Gunicorn se encargará
# app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

