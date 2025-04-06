import json
import os
import random
import shutil
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
DATA_DIR = CURRENT_FILE.parent.parent / "data"

SCENARIO_FOLDER = DATA_DIR / "scenarios"
os.makedirs(SCENARIO_FOLDER, exist_ok=True)

INPUT_PROFESORES = DATA_DIR / "inputOfProfesores.json"
INPUT_SALAS = DATA_DIR / "inputOfSala.json"

def create_scenario_folders():
    """Create folders for each scenario if they don't exist"""
    scenarios = ["small", "medium", "full"]
    for scenario in scenarios:
        os.makedirs(scenario, exist_ok=True)

def load_json_data(filename):
    """Load data from a JSON file"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File {filename} not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: File {filename} contains invalid JSON.")
        return None

def save_json_data(data, filename):
    """Save data to a JSON file with proper formatting"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, ensure_ascii=False, indent=2, fp=f)
    print(f"Created {filename}")

def create_scenario(profesores, salas, scenario_name, profesor_count, sala_count):
    """Create a specific scenario with a subset of professors and classrooms"""
    # Ensure the orden (Turno) values are preserved for the turn-based system
    # by taking the first N professors from the list
    selected_profesores = profesores[:profesor_count]
    
    # Reset the Turno values to be sequential from 0 to N-1
    for i, profesor in enumerate(selected_profesores):
        profesor["Turno"] = i
    
    # Randomly select classrooms
    selected_salas = random.sample(salas, sala_count)
    
    # Save the scenario files
    output_dir = Path(SCENARIO_FOLDER) / scenario_name
    os.makedirs(output_dir, exist_ok=True)
    
    save_json_data(selected_profesores, output_dir / "profesores.json")
    save_json_data(selected_salas, output_dir / "salas.json")
    
    # Also copy any additional configuration files that might be needed
    config_files = ["config.json", "settings.json"]
    for config_file in config_files:
        if os.path.exists(config_file):
            shutil.copy(config_file, output_dir / config_file)
    
    # Create a README with scenario details
    scenario_info = {
        "name": scenario_name,
        "professor_count": profesor_count,
        "classroom_count": sala_count,
        "description": f"{scenario_name.capitalize()} benchmark scenario"
    }
    save_json_data(scenario_info, output_dir / "scenario_info.json")
    
    return selected_profesores, selected_salas

def main():
    # Create scenario folders
    create_scenario_folders()
    
    # Load input data
    profesores = load_json_data(INPUT_PROFESORES)
    salas = load_json_data(INPUT_SALAS)
    
    if not profesores or not salas:
        print("Error loading input files. Exiting.")
        return
    
    # Define scenario sizes
    scenarios = {
        "small": {"profesores": 20, "salas": 15},
        "medium": {"profesores": 80, "salas": 40},
        "full": {"profesores": len(profesores), "salas": len(salas)}
    }
    
    # Check if we have enough data for the scenarios
    if len(profesores) < scenarios["medium"]["profesores"]:
        print(f"Warning: Not enough professors for medium scenario. Using all {len(profesores)} professors.")
        scenarios["medium"]["profesores"] = len(profesores)
    
    if len(salas) < scenarios["medium"]["salas"]:
        print(f"Warning: Not enough classrooms for medium scenario. Using all {len(salas)} classrooms.")
        scenarios["medium"]["salas"] = len(salas)
    
    # Create each scenario
    for scenario_name, counts in scenarios.items():
        print(f"\nGenerating {scenario_name} scenario...")
        profesor_count = min(counts["profesores"], len(profesores))
        sala_count = min(counts["salas"], len(salas))
        
        selected_profesores, selected_salas = create_scenario(
            profesores, salas, scenario_name, profesor_count, sala_count
        )
        
        print(f"Created {scenario_name} scenario with {len(selected_profesores)} professors and {len(selected_salas)} classrooms")
    
    print("\nAll scenarios generated successfully!")

if __name__ == "__main__":
    main()