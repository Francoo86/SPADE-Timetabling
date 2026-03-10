import json
import math

def split_json_file(input_file, output_file):
    """
    Splits a JSON file in half and saves the first half to a new file.
    Handles UTF-8 and other character encodings.
    
    Args:
        input_file (str): Path to the input JSON file
        output_file (str): Path where the output JSON file will be saved
    """
    try:
        # Read the input JSON file with UTF-8 encoding
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle different JSON structures
        if isinstance(data, list):
            # If it's a list, split by length
            halfway = math.ceil(len(data) / 2)
            first_half = data[:halfway]
        elif isinstance(data, dict):
            # If it's a dictionary, split by number of keys
            keys = list(data.keys())
            halfway = math.ceil(len(keys) / 2)
            first_half = {k: data[k] for k in keys[:halfway]}
        else:
            raise ValueError("JSON must contain either a list or dictionary")
            
        # Write the first half to the output file with UTF-8 encoding
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(first_half, f, indent=4, ensure_ascii=False)
            
        print(f"Successfully split JSON file. First half saved to {output_file}")
        
    except UnicodeDecodeError:
        # If UTF-8 fails, try with a different encoding
        try:
            with open(input_file, 'r', encoding='latin-1') as f:
                data = json.load(f)
                
            if isinstance(data, list):
                halfway = math.ceil(len(data) / 2)
                first_half = data[:halfway]
            elif isinstance(data, dict):
                keys = list(data.keys())
                halfway = math.ceil(len(keys) / 2)
                first_half = {k: data[k] for k in keys[:halfway]}
            else:
                raise ValueError("JSON must contain either a list or dictionary")
                
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(first_half, f, indent=4, ensure_ascii=False)
                
            print(f"Successfully split JSON file using latin-1 encoding. First half saved to {output_file}")
            
        except Exception as e:
            print(f"Error: Failed to process file with both UTF-8 and latin-1 encodings: {str(e)}")
            
    except FileNotFoundError:
        print(f"Error: Could not find input file '{input_file}'")
    except json.JSONDecodeError:
        print(f"Error: '{input_file}' is not a valid JSON file")
    except Exception as e:
        print(f"An error occurred: {str(e)}")

# Example usage
if __name__ == "__main__":
    split_json_file("inputOfProfesores.json", "last_half_profesores.json")
    split_json_file("inputOfSala.json", "last_half_salas.json")