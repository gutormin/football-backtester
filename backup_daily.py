import os
import shutil
import datetime
import zipfile

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# Generate filename based on date
date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup_filename = f"backup_base_{date_str}.zip"
backup_filepath = os.path.join(BACKUP_DIR, backup_filename)

print(f"Iniciando backup da base do sistema: {backup_filename}...")

def create_zip(source_dir, output_filename):
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            # Ignore __pycache__, backups folder itself, and .git
            if "backups" in dirs: dirs.remove("backups")
            if "__pycache__" in dirs: dirs.remove("__pycache__")
            if ".git" in dirs: dirs.remove(".git")
            
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)

try:
    create_zip(PROJECT_ROOT, backup_filepath)
    print(f"Backup concluído com sucesso!")
    print(f"Arquivo salvo em: {backup_filepath}")
except Exception as e:
    print(f"Erro ao criar o backup: {e}")
