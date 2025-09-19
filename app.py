import os
from flask import Flask, render_template, request, redirect, url_for
from PIL import Image, ImageChops, ImageEnhance
import exifread

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Función para aplicar ELA
def apply_ela(image_path, quality=90):
    original = Image.open(image_path).convert('RGB')
    resaved_path = image_path.replace(".jpg", "_resaved.jpg")
    original.save(resaved_path, 'JPEG', quality=quality)
    resaved = Image.open(resaved_path)
    ela_image = ImageChops.difference(original, resaved)

    extrema = ela_image.getextrema()
    max_diff = max([ex[1] for ex in extrema])
    scale = 255.0 / max_diff if max_diff != 0 else 1
    ela_image = ImageEnhance.Brightness(ela_image).enhance(scale)

    ela_path = image_path.replace(".jpg", "_ela.jpg")
    ela_image.save(ela_path)
    return ela_path

# Página principal
@app.route('/')
def index():
    return render_template('index.html')

# Ruta para analizar imagen (solo muestra original + metadatos)
@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('index'))

    if file:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)

        # Extraer metadatos
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f)

        metadata = {tag: str(tags[tag]) for tag in tags.keys()}

        return render_template(
            'result.html',
            original_image=filepath,
            metadata=metadata
        )

# Ruta para aplicar ELA después
@app.route('/ela/<filename>')
def ela(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    ela_path = apply_ela(filepath)
    return render_template(
        'ela.html',
        original_image=filepath,
        ela_image=ela_path
    )

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)
