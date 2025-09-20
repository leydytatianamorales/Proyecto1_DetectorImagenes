# app.py
import os
from uuid import uuid4
from datetime import datetime
from flask import Flask, render_template, request, url_for, send_file
from werkzeug.utils import secure_filename
from PIL import Image, ImageChops, ImageEnhance, ExifTags
import imagehash
import piexif
from io import BytesIO

ALLOWED_EXT = {"png", "jpg", "jpeg", "bmp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# ----------------------- Funciones -----------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def extract_metadata(file_obj):
    meta = {}
    try:
        file_obj.seek(0)
        exif_dict = piexif.load(file_obj.read())
        for ifd in exif_dict:
            for tag, val in exif_dict[ifd].items():
                name = piexif.TAGS[ifd].get(tag, {}).get("name", str(tag))
                meta[name] = val.decode() if isinstance(val, bytes) else str(val)
        return meta
    except Exception:
        try:
            file_obj.seek(0)
            img = Image.open(file_obj)
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
        file_obj.seek(0)
        img = Image.open(file_obj).convert("RGB")
        temp_io = BytesIO()
        img.save(temp_io, "JPEG", quality=90)
        temp_io.seek(0)
        comp = Image.open(temp_io)
        diff = ImageChops.difference(img, comp)
        diff = ImageEnhance.Brightness(diff).enhance(30.0)
        ela_io = BytesIO()
        diff.save(ela_io, "PNG")
        ela_io.seek(0)
        return ela_io
    except Exception as e:
        print("ELA error:", e)
        return None

def compare_phash(file_obj1, file_obj2):
    try:
        file_obj1.seek(0)
        file_obj2.seek(0)
        h1 = imagehash.phash(Image.open(file_obj1))
        h2 = imagehash.phash(Image.open(file_obj2))
        return str(h1), str(h2), int(h1 - h2)
    except Exception as e:
        return None, None, f"Error: {e}"

def compare_ela(ela1, ela2):
    try:
        ela1.seek(0)
        ela2.seek(0)
        img1 = Image.open(ela1).convert("L")
        img2 = Image.open(ela2).convert("L")
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

        # Metadata
        meta1 = get_metadata_safe(f1)
        meta2 = get_metadata_safe(f2)

        # Hash perceptual
        h1, h2, diff = compare_phash(f1, f2)

        # ELA
        ela1 = generate_ela(f1)
        ela2 = generate_ela(f2)

        ela_diff_percent = compare_ela(ela1, ela2) if ela1 and ela2 else None

        # Informe de casos de prueba
        informe = []
        informe.append("Informe de Casos de Prueba:")

        # Caso 1: original
        informe.append(f"Caso 1: Imagen original '{f1.filename}'")
        informe.append(f"  - Modelo cámara: {meta1['Model']}")
        informe.append(f"  - Fecha de captura: {meta1['DateCreated']}")
        informe.append(f"  - Fecha de modificación: {meta1['DateModified']}")
        informe.append(f"  - Hash perceptual: referencia")
        informe.append(f"  - ELA: referencia")

        # Caso 2: sospechosa
        informe.append(f"Caso 2: Imagen sospechosa '{f2.filename}'")
        software_detected = meta2['Software'] if meta2['Software'] != "desconocido" else "Software no detectado"
        informe.append(f"  - Software: {software_detected}")
        informe.append(f"  - Fecha de captura: {meta2['DateCreated']}")
        informe.append(f"  - Fecha de modificación: {meta2['DateModified']}")
        informe.append(f"  - Hash perceptual: Diferencia = {diff}")
        if ela_diff_percent is not None:
            informe.append(f"  - ELA comparativa: {ela_diff_percent}% píxeles diferentes")

        # Determinar edición
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
            "informe": "\n".join(informe)
        })

        # Guardar ELA temporal para mostrar en web
        if ela1:
            ela1_url = url_for("show_image", img_id=f"1_{uuid4().hex}")
            context["ela_url1"] = ela1_url
            app.config[ela1_url] = ela1
        if ela2:
            ela2_url = url_for("show_image", img_id=f"2_{uuid4().hex}")
            context["ela_url2"] = ela2_url
            app.config[ela2_url] = ela2

        # Guardar original temporal para mostrar en web
        img1_url = url_for("show_image", img_id=f"o1_{uuid4().hex}")
        img2_url = url_for("show_image", img_id=f"o2_{uuid4().hex}")
        app.config[img1_url] = f1
        app.config[img2_url] = f2
        context["img1_url"] = img1_url
        context["img2_url"] = img2_url

    return render_template("index.html", **context)

# Ruta para servir imágenes temporales
@app.route("/image/<img_id>")
def show_image(img_id):
    key = request.path
    file_obj = app.config.get(key)
    if not file_obj:
        return "Imagen no encontrada", 404
    file_obj.seek(0)
    return send_file(file_obj, mimetype="image/png")

# ----------------------- Run -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
