"""
Test rápido de la API REST
Ejecuta este archivo después de que el servidor esté activo
"""

import requests
import json
import time

BASE_URL = "http://localhost:5000"

def test_health():
    """Test endpoint /api/health"""
    print("\n" + "="*60)
    print("TEST 1: Health Check")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/health")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_info():
    """Test endpoint /api/info"""
    print("\n" + "="*60)
    print("TEST 2: API Info")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/info")
        print(f"Status Code: {response.status_code}")
        data = response.json()
        print(f"Service: {data['service']}")
        print(f"Version: {data['version']}")
        print(f"Endpoints: {list(data['endpoints'].keys())}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_export_missing_params():
    """Test POST /api/export sin parámetros requeridos"""
    print("\n" + "="*60)
    print("TEST 3: Export sin parámetros (debe fallar)")
    print("="*60)
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/export",
            json={}
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 400
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_export_missing_channel():
    """Test POST /api/export sin channel_id"""
    print("\n" + "="*60)
    print("TEST 4: Export sin channel_id (debe fallar)")
    print("="*60)
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/export",
            json={"token": "test_token"}
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 400
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Ejecutar todos los tests"""
    print("\n")
    print("🧪 Discord Exporter Pro - Test Suite")
    print("="*60)
    print(f"Testing API at: {BASE_URL}")
    print("="*60)
    
    # Verificar conexión inicial
    try:
        requests.get(f"{BASE_URL}/api/health", timeout=2)
    except:
        print("\n❌ No se puede conectar a la API")
        print("Asegúrate de que el servidor está ejecutándose:")
        print("   python discord_exporter_pro_CLI.py")
        return
    
    results = {
        "Health Check": test_health(),
        "API Info": test_info(),
        "Export sin params": test_export_missing_params(),
        "Export sin channel": test_export_missing_channel(),
    }
    
    # Resumen
    print("\n" + "="*60)
    print("📊 RESUMEN DE TESTS")
    print("="*60)
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests pasaron")
    
    if passed == total:
        print("\n🎉 Todos los tests pasaron correctamente!")
        print("\n💡 Próximos pasos:")
        print("   1. Obtén un token de Discord válido")
        print("   2. Obtén un ID de canal válido")
        print("   3. Haz una solicitud POST a /api/export")
        print("   4. Consulta API_DOCUMENTATION.md para más información")
    else:
        print(f"\n⚠️  {total - passed} test(s) fallaron")

if __name__ == "__main__":
    main()
