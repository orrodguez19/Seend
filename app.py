import os
import subprocess
from flask import Flask, jsonify, request

app = Flask(__name__)

# Ruta para la carpeta de almacenamiento
MOUNT_PATH = '/tmp/mounted_storage'  # Usamos una ruta temporal para Render
DISK_FILE = '/tmp/storage.img'  # También lo mantenemos en una ruta temporal
DISK_SIZE = '500M'  # Tamaño del disco

# Verificar si el archivo de disco existe, si no, crearlo
def create_disk():
    if not os.path.exists(DISK_FILE):
        # Crear un archivo de disco vacío
        print("Creando archivo de disco de 500 MB...")
        subprocess.run(['dd', 'if=/dev/zero', 'of=' + DISK_FILE, 'bs=1M', 'count=500'], check=True)

        # Crear un sistema de archivos en el archivo de disco
        subprocess.run(['mkfs.ext4', DISK_FILE], check=True)

        # Crear la carpeta de montaje si no existe
        if not os.path.exists(MOUNT_PATH):
            os.makedirs(MOUNT_PATH)

        # Montar el disco
        subprocess.run(['mount', '-o', 'loop', DISK_FILE, MOUNT_PATH], check=True)
        print("Disco creado y montado exitosamente.")
    else:
        print("El archivo de disco ya existe. Montando...")

        # Si el archivo de disco ya existe, solo lo montamos
        if not os.path.ismount(MOUNT_PATH):
            subprocess.run(['mount', '-o', 'loop', DISK_FILE, MOUNT_PATH], check=True)
            print("Disco montado exitosamente.")
        else:
            print("El disco ya está montado.")

# Ruta para obtener información sobre el almacenamiento
@app.route('/storage', methods=['GET'])
def storage_info():
    # Usar df para obtener detalles del almacenamiento en la carpeta de montaje
    result = subprocess.run(['df', '-h', MOUNT_PATH], stdout=subprocess.PIPE)
    output = result.stdout.decode()

    # Parsear la salida de df para extraer los datos
    lines = output.splitlines()
    storage_details = lines[1].split()  # La segunda línea contiene la información que necesitamos
    total, used, available = storage_details[1], storage_details[2], storage_details[3]

    return jsonify({
        'total_storage': total,
        'used_storage': used,
        'available_storage': available
    })

# Ruta para subir archivos
@app.route('/upload', methods=['POST'])
def upload_file():
    # Verifica si el archivo se sube correctamente
    if 'file' not in request.files:
        return jsonify({"error": "No se proporcionó archivo"}), 400

    file = request.files['file']
    file_path = os.path.join(MOUNT_PATH, file.filename)

    # Guardar el archivo en la carpeta de montaje
    file.save(file_path)

    return jsonify({"message": "Archivo subido correctamente!"}), 200

# Ruta para listar los archivos disponibles
@app.route('/files', methods=['GET'])
def list_files():
    files = os.listdir(MOUNT_PATH)
    return jsonify({"files": files})

# Ruta para eliminar un archivo
@app.route('/delete/<filename>', methods=['DELETE'])
def delete_file(filename):
    file_path = os.path.join(MOUNT_PATH, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return jsonify({"message": f"Archivo {filename} eliminado exitosamente!"}), 200
    else:
        return jsonify({"message": "Archivo no encontrado!"}), 404

if __name__ == '__main__':
    # Verificar y crear el disco al iniciar
    create_disk()

    # Iniciar el servidor Flask en el puerto 10000
    app.run(host='0.0.0.0', port=10000)