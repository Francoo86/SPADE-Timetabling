import json

def load_data(profesores_json, salas_json):
    """
    Load and parse the JSON data for professors and rooms.
    """
    try:
        profesores = json.loads(profesores_json)
        salas = json.loads(salas_json)
        return profesores, salas
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None, None

def find_matches(profesores, salas):
    """
    Find matches between professors' subjects and room assignments.
    """
    matches = []
    mismatches = []
    
    # Check if we have a single professor or a list
    if isinstance(profesores, dict):
        profesores = [profesores]
    
    # Check if we have a single room or a list
    if isinstance(salas, dict):
        salas = [salas]
    
    # Iterate through each professor
    for profesor in profesores:
        nombre_profesor = profesor.get("Nombre", "Unknown")
        asignaturas_profesor = profesor.get("Asignaturas", [])
        
        # Iterate through each subject for this professor
        for asignatura_prof in asignaturas_profesor:
            nombre_asignatura_prof = asignatura_prof.get("Nombre", "")
            dia_prof = asignatura_prof.get("Dia", "")
            bloque_prof = asignatura_prof.get("Bloque", -1)
            sala_prof = asignatura_prof.get("Sala", "")
            
            found_match = False
            
            # Iterate through each room
            for sala in salas:
                codigo_sala = sala.get("Codigo", "")
                asignaturas_sala = sala.get("Asignaturas", [])
                
                # Check if this room matches the professor's assigned room
                if sala_prof == codigo_sala:
                    # Iterate through each subject in this room
                    for asignatura_sala in asignaturas_sala:
                        nombre_asignatura_sala = asignatura_sala.get("Nombre", "")
                        dia_sala = asignatura_sala.get("Dia", "")
                        bloque_sala = asignatura_sala.get("Bloque", -1)
                        
                        # Check if the subject, day, and block match
                        if (nombre_asignatura_prof == nombre_asignatura_sala and 
                            dia_prof == dia_sala and 
                            bloque_prof == bloque_sala):
                            
                            matches.append({
                                "Profesor": nombre_profesor,
                                "Asignatura": nombre_asignatura_prof,
                                "Sala": sala_prof,
                                "Dia": dia_prof,
                                "Bloque": bloque_prof,
                                "Match": True
                            })
                            found_match = True
                            break
                
                if found_match:
                    break
            
            # If no match was found for this subject
            if not found_match:
                mismatches.append({
                    "Profesor": nombre_profesor,
                    "Asignatura": nombre_asignatura_prof,
                    "Sala_Asignada": sala_prof,
                    "Dia": dia_prof,
                    "Bloque": bloque_prof,
                    "Match": False,
                    "Reason": "No matching room-subject found"
                })
    
    # Check if professors are assigned to rooms that match the schedule in salas
    # This is now just an informational check, not a mismatch since professors are not required
    rooms_with_no_professors = []
    
    for sala in salas:
        codigo_sala = sala.get("Codigo", "")
        asignaturas_sala = sala.get("Asignaturas", [])
        
        for asignatura_sala in asignaturas_sala:
            nombre_asignatura_sala = asignatura_sala.get("Nombre", "")
            dia_sala = asignatura_sala.get("Dia", "")
            bloque_sala = asignatura_sala.get("Bloque", -1)
            
            found_match = False
            
            for profesor in profesores:
                asignaturas_profesor = profesor.get("Asignaturas", [])
                
                for asignatura_prof in asignaturas_profesor:
                    nombre_asignatura_prof = asignatura_prof.get("Nombre", "")
                    dia_prof = asignatura_prof.get("Dia", "")
                    bloque_prof = asignatura_prof.get("Bloque", -1)
                    sala_prof = asignatura_prof.get("Sala", "")
                    
                    if (nombre_asignatura_sala == nombre_asignatura_prof and 
                        dia_sala == dia_prof and 
                        bloque_sala == bloque_prof and 
                        codigo_sala == sala_prof):
                        
                        found_match = True
                        break
                
                if found_match:
                    break
            
            if not found_match:
                rooms_with_no_professors.append({
                    "Sala": codigo_sala,
                    "Asignatura": nombre_asignatura_sala,
                    "Dia": dia_sala,
                    "Bloque": bloque_sala,
                    "Has_Professor": False
                })
    
    return matches, mismatches

def print_results(matches, mismatches):
    """
    Print the matching results in a readable format.
    """
    print("\n=== MATCHES ===")
    if matches:
        for match in matches:
            print(f"[OK] Professor: {match['Profesor']}")
            print(f"  Subject: {match['Asignatura']}")
            print(f"  Room: {match['Sala']}")
            print(f"  Day: {match['Dia']}, Block: {match['Bloque']}")
            print()
    else:
        print("No matches found.")
    
    print("\n=== MISMATCHES ===")
    if mismatches:
        for mismatch in mismatches:
            if "Profesor" in mismatch:
                print(f"[FAIL] Professor: {mismatch['Profesor']}")
                print(f"  Subject: {mismatch['Asignatura']}")
                print(f"  Assigned Room: {mismatch['Sala_Asignada']}")
                print(f"  Day: {mismatch['Dia']}, Block: {mismatch['Bloque']}")
                print(f"  Reason: {mismatch['Reason']}")
                print()
            else:
                print(f"[FAIL] Room: {mismatch['Sala']}")
                print(f"  Subject: {mismatch['Asignatura']}")
                print(f"  Day: {mismatch['Dia']}, Block: {mismatch['Bloque']}")
                print(f"  Reason: {mismatch['Reason']}")
                print()
    else:
        print("No mismatches found.")

def validate_scenarios(scenario : str = "small"):
    import json
    import os
    
    CURRENT_FILE = os.path.dirname(os.path.abspath(__file__))
    CURRENT_SCENARIO = os.path.join(CURRENT_FILE, "agent_output", scenario)
    # Example usage with your JSON data
    profesores_json = json.load(open(os.path.join(CURRENT_SCENARIO, "Horarios_asignados.json"), encoding="latin-1"))
    
    salas_json = json.load(open(os.path.join(CURRENT_SCENARIO, "Horarios_salas.json"), encoding="latin-1"))
    
    # Load the data
    # profesores, salas = load_data(profesores_json, salas_json)
    
    if profesores_json and salas_json:
        # Find matches and mismatches
        matches, mismatches = find_matches(profesores_json, salas_json)
        
        # Print the results
        print_results(matches, mismatches)
    else:
        print("Failed to process the data.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate professor and room assignments.")
    parser.add_argument("--scenario", type=str, default="small", help="Scenario to validate (default: small), choices: small, medium, full.")
    args = parser.parse_args()
    
    validate_scenarios(args.scenario)