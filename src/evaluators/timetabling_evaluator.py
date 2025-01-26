from typing import Dict, List
from objects.static.agent_enums import Actividad, TipoContrato

# Constants
MAX_BLOQUE_DIURNO = 9
OPTIMAL_OCCUPANCY_MIN = 0.75
OPTIMAL_OCCUPANCY_MAX = 0.95
MIN_STUDENTS = 9
MAX_STUDENTS = 70
MEETING_ROOM_THRESHOLD = 10

# Weights for different constraints
WEIGHTS = {
    'capacity': 0.25,
    'time_slot': 0.20,
    'campus': 0.20,
    'continuity': 0.15,
    'activity_type': 0.20
}

class TimetablingEvaluator:
    @staticmethod
    def calculate_satisfaction(
            room_capacity: int,
            students_count: int,
            nivel: int,
            campus: str,
            preferred_campus: str,
            block: int,
            existing_blocks: Dict[str, List[int]],
            contrato: 'TipoContrato',
            activity: 'Actividad'
    ) -> int:
        """
        Calculate satisfaction score for a room assignment based on multiple criteria.
        
        Args:
            room_capacity: Capacity of the room
            students_count: Number of students
            nivel: Academic level
            campus: Campus of the room
            preferred_campus: Preferred campus
            block: Time block
            existing_blocks: Dictionary of existing blocks by day
            contrato: Contract type (TipoContrato enum)
            activity: Activity type (Actividad enum)
            
        Returns:
            Integer satisfaction score from 1 to 10
        """
        # Critical capacity violation
        if students_count > room_capacity:
            return 1

        # Small class handling
        if students_count < MIN_STUDENTS:
            if room_capacity < MEETING_ROOM_THRESHOLD:
                meeting_room_ratio = students_count / room_capacity
                if 0.5 <= meeting_room_ratio <= 0.9:
                    return 5  # Good fit for small class
                return 3  # Acceptable but not optimal
            return 2  # Small class in regular room - not ideal

        # Very large class check
        if students_count > MAX_STUDENTS:
            return 2  # Should be split into parallel sections

        # Calculate individual scores
        capacity_score = TimetablingEvaluator._evaluate_capacity(room_capacity, students_count)
        time_slot_score = TimetablingEvaluator._evaluate_time_slot(nivel, block)
        campus_score = TimetablingEvaluator._evaluate_campus(campus, preferred_campus, existing_blocks)
        continuity_score = TimetablingEvaluator._evaluate_continuity(existing_blocks, contrato)
        activity_score = TimetablingEvaluator._evaluate_activity_type(activity, block)

        # Calculate weighted average
        weighted_score = (
            capacity_score * WEIGHTS['capacity'] +
            time_slot_score * WEIGHTS['time_slot'] +
            campus_score * WEIGHTS['campus'] +
            continuity_score * WEIGHTS['continuity'] +
            activity_score * WEIGHTS['activity_type']
        ) * 10

        # Round to nearest integer and ensure score is between 1-10
        return max(1, min(10, round(weighted_score)))

    @staticmethod
    def _evaluate_capacity(room_capacity: int, students_count: int) -> float:
        """Evaluate room capacity utilization."""
        if students_count < MEETING_ROOM_THRESHOLD:
            if room_capacity < MEETING_ROOM_THRESHOLD:
                meeting_room_ratio = students_count / room_capacity
                if 0.5 <= meeting_room_ratio <= 0.9:
                    return 1.0  # Perfect fit for small class in meeting room
                return 0.8  # Still good for meeting room
            else:
                if room_capacity <= students_count * 5:
                    return 0.7  # Acceptable if room isn't too oversized
                return 0.5  # Penalty for very oversized room

        occupancy_ratio = students_count / room_capacity

        # Optimal efficiency: 75-95% room capacity
        if OPTIMAL_OCCUPANCY_MIN <= occupancy_ratio <= OPTIMAL_OCCUPANCY_MAX:
            return 1.0
        # Underutilized: <75% capacity
        elif occupancy_ratio < OPTIMAL_OCCUPANCY_MIN:
            return 0.7 + (occupancy_ratio / OPTIMAL_OCCUPANCY_MIN) * 0.3
        # Near capacity: >95% but <= 100%
        elif occupancy_ratio <= 1.0:
            return 0.8
        # Over capacity should never happen as it's caught earlier
        else:
            return 0.1

    @staticmethod
    def _evaluate_time_slot(nivel: int, block: int) -> float:
        """Evaluate time slot preferences based on academic level."""
        # Constraint 1: Only blocks 1-9 (8:00-18:30)
        if block < 1 or block > MAX_BLOQUE_DIURNO:
            return 0.0

        # Constraints 3 & 7: Level-based time preferences
        is_first_year = nivel <= 2
        is_odd_level = nivel % 2 == 1

        # First year students preferably in morning
        if is_first_year:
            return 1.0 if block <= 4 else 0.6

        # Other levels: Odd years morning, Even years afternoon
        return 1.0 if (is_odd_level and block <= 4) or (not is_odd_level and block >= 5) else 0.7

    @staticmethod
    def _evaluate_activity_type(activity: 'Actividad', block: int) -> float:
        """Evaluate activity type preferences for different time blocks."""
        # Constraint 2: Theory classes in morning blocks (1-4)
        if activity == Actividad.TEORIA:
            return 1.0 if block <= 4 else 0.6

        # Labs/workshops/practices better in afternoon
        if activity in (Actividad.LABORATORIO, Actividad.TALLER, Actividad.PRACTICA):
            return 1.0 if block >= 5 else 0.7

        # Ayudantias and Tutorias are more flexible
        if activity in (Actividad.AYUDANTIA, Actividad.TUTORIA):
            return 1.0

        return 0.8  # Default case

    @staticmethod
    def _evaluate_campus(
            campus: str,
            preferred_campus: str,
            existing_blocks: Dict[str, List[int]]
    ) -> float:
        """Evaluate campus assignment preferences."""
        # Constraint 4: Campus transitions
        if campus != preferred_campus:
            # Check if there are already classes in different campuses
            has_other_campus = sum(len(blocks) for blocks in existing_blocks.values()) > 0

            if has_other_campus:
                return 0.5  # Penalty for multiple campus transitions

        return 1.0 if campus == preferred_campus else 0.7

    @staticmethod
    def _evaluate_continuity(
            existing_blocks: Dict[str, List[int]],
            tipo_contrato: 'TipoContrato'
    ) -> float:
        """Evaluate continuity of blocks."""
        if tipo_contrato == TipoContrato.JORNADA_PARCIAL:
            return 1.0  # No continuity restrictions for part-time

        score = 1.0
        for blocks in existing_blocks.values():
            if len(blocks) < 2:
                continue

            sorted_blocks = sorted(blocks)

            # Evaluate gaps between blocks
            for i in range(1, len(sorted_blocks)):
                gap = sorted_blocks[i] - sorted_blocks[i-1] - 1

                if gap > 1:
                    # Penalize more than one free block
                    score *= 0.6
                elif gap == 1:
                    # One free block is acceptable but not optimal
                    score *= 0.9
                # Consecutive blocks maintain score = 1.0

        return score