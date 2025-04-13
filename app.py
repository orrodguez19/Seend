from flask import Flask, request, send_from_directory, jsonify
import os

app = Flask(__name__)

# Configura la carpeta donde se almacenarán los archivos subidos
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Asegúrate de que la carpeta de uploads exista
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Ruta para subir archivos
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Guardar el archivo en la carpeta de uploads
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(file_path)
    
    return jsonify({"message": "File uploaded successfully", "file_path": file_path}), 200

# Ruta para descargar archivos
@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

# Ruta para listar archivos disponibles
@app.route('/list', methods=['GET'])
def list_files():
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    return jsonify({"files": files})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=10000)