# app.py
import os
from uuid import uuid4
from datetime import datetime
from io import BytesIO
from flask import Flask, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename
from PIL import Image, ImageChops, ImageEnhance, ExifTags
import imagehash
import piexif

ALLOWED_EXT = {"png", "jpg", "jpeg", "bmp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# ----------------------- Almacenamiento temporal -----------------------
images_storage = {}  # Diccionario temporal: img_id -> BytesIO + info

# ----------------------- Funciones -----------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def extract_metadata(path_or_file):
    meta = {}
    try:
        exif_dict = piexif.load(path_or_file)
        for ifd in exif_dict:
            for tag, val in exif_dict[ifd].items():
                name = piexif.TAGS[ifd].get(tag, {}).get("name", str(tag))
                meta[name] = val.decode() if isinstance(val, bytes) else str(val)
        return meta
    except Exception:
        try:
            img = Image.open(path_or_file)
            raw = img._getexif()
            if raw:
                for tag, val in raw.items():
                    name = ExifTags.TAGS.get(tag, tag)
                    meta[name] = str(val)
            return meta
        except Exception:
            return {}

def get_metadata_safe(file_obj):
    meta = extract_metadata(file_obj)
    data = {}
    data["Model"] = meta.get("Model") or meta.get("CameraModelName") or "desconocido"
    data["DateCreated"] = meta.get("DateTimeOriginal") or meta.get("DateTime") or "desconocida"
    exif_mod = meta.get("ModifyDate") or meta.get("DateTimeDigitized")
    if exif_mod:
        data["DateModified"] = exif_mod
    else:
        data["DateModified"] = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
    data["Software"] = meta.get("Software", "desconocido")
    data["all_metadata"] = meta
    return data

def generate_ela(file_obj):
    try:
        img = Image.open(file_obj).convert("RGB")
        temp = BytesIO()
        img.save(temp, "JPEG", quality=90)
        temp.seek(0)
        comp = Image.open(temp)
        diff = ImageChops.difference(img, comp)
        diff = ImageEnhance.Brightness(diff).enhance(30.0)
        ela_io = BytesIO()
        diff.save(ela_io, "PNG")
        ela_io.seek(0)
        return ela_io
    except Exception as e:
        print("ELA error:", e)
        return None

def compare_phash(file1, file2):
    try:
        h1 = imagehash.phash(Image.open(file1))
        h2 = imagehash.phash(Image.open(file2))
        return str(h1), str(h2), int(h1 - h2)
    except Exception as e:
        return None, None, f"Error: {e}"

def compare_ela(file1, file2):
    try:
        img1 = Image.open(file1).convert("L")
        img2 = Image.open(file2).convert("L")
        diff = ImageChops.difference(img1, img2)
        total_pixels = diff.size[0] * diff.size[1]
        nonzero = sum(1 for v in diff.getdata() if v != 0)
        percent = (nonzero / total_pixels) * 100
        return round(percent, 2)
    except Exception:
        return None

# ----------------------- Rutas -----------------------
@app.route("/", methods=["GET", "POST"])
def index():
    context = {"current_year": datetime.now().year}
    if request.method == "POST":
        f1 = request.files.get("original")
        f2 = request.files.get("sospechosa")
        if not f1 or not f2 or not allowed_file(f1.filename) or not allowed_file(f2.filename):
            context["error"] = "Carga dos imágenes válidas (jpg/png...)"
            return render_template("index.html", **context)

        # Guardar temporalmente
        id1 = uuid4().hex
        id2 = uuid4().hex
        images_storage[id1] = {"file": BytesIO(f1.read()), "filename": f1.filename}
        images_storage[id2] = {"file": BytesIO(f2.read()), "filename": f2.filename}

        # Reiniciar puntero
        images_storage[id1]["file"].seek(0)
        images_storage[id2]["file"].seek(0)

        meta1 = get_metadata_safe(images_storage[id1]["file"])
        meta2 = get_metadata_safe(images_storage[id2]["file"])
        images_storage[id1]["file"].seek(0)
        images_storage[id2]["file"].seek(0)

        h1, h2, diff = compare_phash(images_storage[id1]["file"], images_storage[id2]["file"])
        images_storage[id1]["file"].seek(0)
        images_storage[id2]["file"].seek(0)

        ela_io1 = generate_ela(images_storage[id1]["file"])
        ela_io2 = generate_ela(images_storage[id2]["file"])
        ela_id1 = uuid4().hex
        ela_id2 = uuid4().hex
        images_storage[ela_id1] = {"file": ela_io1, "filename": f"ELA_{f1.filename}"}
        images_storage[ela_id2] = {"file": ela_io2, "filename": f"ELA_{f2.filename}"}

        ela_diff_percent = compare_ela(ela_io1, ela_io2) if ela_io1 and ela_io2 else None

        # Informe de casos de prueba
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
        if ela_diff_percent is not None:
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
            "informe": "\n".join(informe),
            "img1_url": url_for('serve_image', img_id=id1),
            "img2_url": url_for('serve_image', img_id=id2),
            "ela_url1": url_for('serve_image', img_id=ela_id1),
            "ela_url2": url_for('serve_image', img_id=ela_id2),
        })

    return render_template("index.html", **context)

@app.route("/image/<img_id>")
def serve_image(img_id):
    img_info = images_storage.get(img_id)
    if not img_info or not img_info["file"]:
        return "Imagen no encontrada", 404
    img_info["file"].seek(0)
    return send_file(img_info["file"], attachment_filename=img_info["filename"], mimetype='image/png')

# ----------------------- Run -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
