import sys
import os
import time
import webbrowser
import subprocess
import threading

# Add root folder to python path so uvicorn can find backend.app
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def check_dependencies():
    """Verifies that all required Python packages are installed, and attempts pip install if not."""
    required_packages = {
        'pandas': 'pandas',
        'numpy': 'numpy',
        'fastapi': 'fastapi',
        'uvicorn': 'uvicorn',
        'requests': 'requests'
    }
    
    missing_packages = []
    for pkg_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(pkg_name)
            
    if missing_packages:
        print("==" * 30)
        print(f"Aviso: Dependências faltando detectadas: {', '.join(missing_packages)}")
        print("Tentando instalar dependências via pip...")
        print("==" * 30)
        try:
            requirements_path = os.path.join(project_root, 'requirements.txt')
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", requirements_path])
            print("\nDependências instaladas com sucesso!\n")
        except Exception as e:
            print(f"\nErro ao instalar dependências automaticamente: {e}")
            print("Por favor, instale manualmente no seu terminal:")
            print("  pip install -r requirements.txt")
            print("==" * 30)
            sys.exit(1)

def open_browser():
    """Waits for the server to start, then opens the browser."""
    time.sleep(1.8)
    url = "http://127.0.0.1:8000"
    print("\n" + "=" * 60)
    print(f" PAINEL PRONTO: Acesse {url} se o seu navegador não abrir automaticamente.")
    print("=" * 60 + "\n")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Não foi possível abrir o navegador automaticamente: {e}")

if __name__ == '__main__':
    # Ensure current directory is the script directory
    os.chdir(project_root)
    
    print("Iniciando Sports Betting Backtester Pro...")
    check_dependencies()
    
    # Start browser opener in a background thread
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    # Run the server
    try:
        import uvicorn
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=True, log_level="info")
    except KeyboardInterrupt:
        print("\nServidor encerrado pelo usuário. Até logo!")
        sys.exit(0)
    except Exception as e:
        print(f"\nFalha ao iniciar o servidor: {e}")
        sys.exit(1)
