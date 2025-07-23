#!/usr/bin/env python3
"""
Test script to verify JWT library works correctly.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def test_jwt_library():
    """Test that the JWT library works correctly."""
    print("🐧 Testing JWT Library")
    print("=" * 30)
    
    # Test PyJWT import and encoding
    try:
        import jwt as pyjwt
        
        # Test payload
        payload = {
            'iat': 1234567890,
            'exp': 1234567890 + 600,
            'iss': 'test-app-id'
        }
        
        # Test key (dummy RSA private key for testing)
        test_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAuGbXWiK3dQTyCbX5xdE4yCuYp0yyTn1lwdxPbQJlnO8CuL6+
xMvvBK7t4bBOH6D7MhN9GdAXPnOFxc4VaILpRSJ9QlYZcnbhFhZfzQGzgCW7pWnQ
test-key-content-here
-----END RSA PRIVATE KEY-----"""
        
        # This should work if PyJWT is properly imported
        token = pyjwt.encode(payload, test_private_key, algorithm='RS256')
        print(f"✅ JWT encoding successful: {token[:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ JWT encoding failed: {e}")
        return False

if __name__ == "__main__":
    success = test_jwt_library()
    
    print("\n" + "=" * 30)
    if success:
        print("✅ JWT library test PASSED!")
    else:
        print("❌ JWT library test FAILED!")
    
    sys.exit(0 if success else 1)