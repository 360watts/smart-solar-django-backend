"""
Quick check to see which servers are accessible
"""
import socket

def check_port(host, port, name):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex((host, port))
    sock.close()
    if result == 0:
        print(f"✅ {name} is running on {host}:{port}")
        return True
    else:
        print(f"❌ {name} is NOT running on {host}:{port}")
        return False

print("=== Checking Local Servers ===\n")
django_running = check_port('localhost', 8000, 'Django Backend')
react_running = check_port('localhost', 3000, 'React Frontend')

print("\n=== Next Steps ===")
if not django_running:
    print("\n1. Start Django server:")
    print("   cd c:\\Users\\Win11\\smart-solar-workspace\\smart-solar-django-backend")
    print("   python manage.py runserver")

if react_running:
    print("\n2. Restart React dev server (in the terminal running npm start):")
    print("   Press Ctrl+C to stop")
    print("   Then run: npm start")
else:
    print("\n2. Start React dev server:")
    print("   cd c:\\Users\\Win11\\smart-solar-workspace\\smart-solar-react-frontend")
    print("   npm start")

print("\n💡 Or test directly on production:")
print("   https://smart-solar-django-backend.vercel.app/api/devices/")
