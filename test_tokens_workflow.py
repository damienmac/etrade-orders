"""
This script tests the token workflow:
1. It checks if etrade_tokens.py exists
2. If it exists, it displays its content
3. It explains how to test the full workflow

This helps verify that the token generation and import process works correctly.
"""

import os
import importlib
import sys

def test_tokens_workflow():
    print("Testing token workflow...")
    
    # Check if etrade_tokens.py exists
    if os.path.exists('etrade_tokens.py'):
        print("\nFound etrade_tokens.py file.")
        
        # Try to import the tokens
        try:
            # Force reload if the module was already imported
            if 'etrade_tokens' in sys.modules:
                importlib.reload(sys.modules['etrade_tokens'])
            else:
                import etrade_tokens
                
            print("Successfully imported tokens from etrade_tokens.py")
            print(f"Current tokens: {etrade_tokens.tokens}")
        except Exception as e:
            print(f"Error importing etrade_tokens.py: {e}")
    else:
        print("\netrade_tokens.py not found.")
        print("To test the full workflow:")
        print("1. Run tokens.py to generate etrade_tokens.py")
        print("2. Run main.py to verify it imports the tokens correctly")
    
    print("\nTo test the complete workflow:")
    print("1. Run 'python tokens.py' and follow the authentication process")
    print("2. Verify that etrade_tokens.py is created")
    print("3. Run 'python main.py' and check that it uses the tokens from etrade_tokens.py")
    print("   (Look for the message 'Using tokens from etrade_tokens.py')")

if __name__ == "__main__":
    test_tokens_workflow()