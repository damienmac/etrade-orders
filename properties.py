def load_properties(file_path='etrade.properties'):
    """
    Read the etrade.properties file and return a dictionary with the same keys.
    Also creates global variables with the same names as the keys.
    
    Args:
        file_path (str): Path to the properties file
        
    Returns:
        dict: Dictionary containing the properties
    """
    properties = {}
    
    try:
        with open(file_path, 'r') as file:
            for line in file:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                
                # Split by the first equals sign
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    
                    # Store in the dictionary
                    properties[key] = value
                    
                    # Create a global variable with the same name
                    globals()[key] = value
    except FileNotFoundError:
        print(f"Error: Properties file '{file_path}' not found.")
    except Exception as e:
        print(f"Error reading properties file: {e}")
    
    return properties


if __name__ == '__main__':
    # Test the function
    props = load_properties()
    print("Loaded properties:")
    for key, value in props.items():
        print(f"{key} = {value}")