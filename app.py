from flask import Flask, request, send_from_directory, jsonify
import os
import shutil

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

# Ruta para eliminar archivo
@app.route('/delete/<filename>', methods=['DELETE'])
def delete_file(filename):
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        os.remove(file_path)
        return jsonify({"message": f"File {filename} deleted successfully"}), 200
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

# Ruta para ver información del almacenamiento
@app.route('/storage', methods=['GET'])
def storage_info():
    total, used, free = shutil.disk_usage(app.config['UPLOAD_FOLDER'])
    
    total_gb = total // (2**30)  # Total en GB
    used_gb = used // (2**30)    # Usado en GB
    free_gb = free // (2**30)    # Libre en GB
    
    return jsonify({
        "total_storage": f"{total_gb} GB",
        "used_storage": f"{used_gb} GB",
        "free_storage": f"{free_gb} GB"
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=10000)