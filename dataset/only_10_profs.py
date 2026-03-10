import json

def save_last_samples(input_file_path, output_file_path, num_samples=10):
    # Read the JSON file
    with open(input_file_path, 'r') as file:
        data = json.load(file)
    
    # Get the last n samples
    last_samples = data[-num_samples:]
    
    # Save to a new JSON file with proper formatting
    with open(output_file_path, 'w', encoding='utf-8') as file:
        json.dump(last_samples, file, indent=2, ensure_ascii=False)
    
    print(f"Successfully saved last {len(last_samples)} samples to {output_file_path}")

# Example usage
if __name__ == "__main__":
    input_file = "fhp_part1.json"  # Replace with your input file path
    output_file = "ultimatum_profesores.json"  # Replace with desired output file path
    save_last_samples(input_file, output_file)