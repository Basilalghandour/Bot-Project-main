# Bot-Project/orders/district_matching.py

import re
import difflib
from .models import BostaCity, BostaDistrict

def normalize_district_name(name: str):
    """
    Cleans and standardizes a district name, including handling common
    "Franco-Arabic" number-to-letter substitutions and joined "el/al" prefixes.
    """
    if not isinstance(name, str):
        return ""
    
    name = name.lower().strip()

    # Handle "Franco-Arabic" number substitutions
    name = name.replace('3', 'a')
    name = name.replace('7', 'h')
    name = name.replace('5', 'kh')
    name = name.replace('8', 'gh')

    # Handle both hyphenated and joined "el/al" prefixes
    if name.startswith("al-"):
        name = name[3:]
    elif name.startswith("el-"):
        name = name[3:]
    elif name.startswith("al"):
        name = name[2:]
    elif name.startswith("el"):
        name = name[2:]
    
    name = re.sub(r'^(ال|أل)', '', name).strip()
    name = re.sub(r'[^a-z0-9\s\u0600-\u06FF]', '', name, flags=re.UNICODE)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def find_best_district_match(input_district_name: str, city: BostaCity, confidence_threshold=0.70):
    """
    Finds the best matching BostaDistrict using a more robust algorithm that
    averages the similarity of the best-matching words (tokens) against both
    English and Arabic names.
    """
    if not input_district_name or not city:
        return None

    normalized_input = normalize_district_name(input_district_name)

    # Fetch all districts for the city
    all_districts_in_city = list(BostaDistrict.objects.filter(city=city))
    
    if not all_districts_in_city:
        print(f"DISTRICT_MATCH: FAILED. No districts registered for city '{city.name}'.")
        return None

    best_match_district = None
    highest_score = 0.0

    # Smart Token Matching with Averaged Similarity
    input_tokens = set(normalized_input.split())
    if not input_tokens:
        return None

    for district in all_districts_in_city:
        # Check against both English and Arabic names
        names_to_check = [district.name]
        if district.name_ar:
            names_to_check.append(district.name_ar)

        for db_name in names_to_check:
            normalized_db_name = normalize_district_name(db_name)
            if not normalized_db_name:
                continue

            db_tokens = set(normalized_db_name.split())
            if not db_tokens:
                continue

            total_similarity = 0
            for in_token in input_tokens:
                best_match_for_token = difflib.get_close_matches(in_token, db_tokens, n=1, cutoff=0.1)
                if best_match_for_token:
                    similarity = difflib.SequenceMatcher(None, in_token, best_match_for_token[0]).ratio()
                    total_similarity += similarity
            
            score = total_similarity / len(input_tokens)

            if normalized_input and normalized_db_name and normalized_input[0] == normalized_db_name[0]:
                score *= 1.15

            if score > highest_score:
                highest_score = score
                best_match_district = district

    # Final check
    if best_match_district and highest_score >= confidence_threshold:
        print(f"DISTRICT_MATCH: SUCCESS (Averaged Token Match). Input '{input_district_name}' -> '{best_match_district.name}'. Score: {highest_score:.2f}")
        return best_match_district
            
    print(f"DISTRICT_MATCH: FAILED. No match found for '{input_district_name}'. Best score was {highest_score:.2f} (Threshold: {confidence_threshold}).")
    return None