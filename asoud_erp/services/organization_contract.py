def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("Invalid organization rows (maximum 500)")
    positions, employees = {}, set()
    normalized = []
    for source in rows:
        if not isinstance(source, dict):
            raise ValueError("Each organization row must be an object")
        row = {key: str(source.get(key) or "").strip()
               for key in ("code", "title", "parent", "department", "employee")}
        if "department_id" in source:
            row["department_id"] = str(source.get("department_id") or "").strip()
        if "occupants" in source:
            occupants = source["occupants"]
            if not isinstance(occupants, list) or any(not isinstance(x, str) or not x.strip() for x in occupants):
                raise ValueError("Invalid occupants")
            occupants = [x.strip() for x in occupants]
            if len(set(occupants)) != len(occupants):
                raise ValueError("Duplicate occupant")
            capacity = source.get("capacity", 1)
            if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
                raise ValueError("Capacity must be a positive integer")
            if len(occupants) > capacity:
                raise ValueError("Capacity is below the active assignment count")
            row.update(occupants=occupants, capacity=capacity,
                duties=str(source.get("duties") or "").strip())
            # Legacy compatibility field is not authoritative for v2 rows.
            row["employee"] = ""
            if "assignment_history" in source:
                row["assignment_history"] = source["assignment_history"]
        if not row["code"] or not row["title"] or row["code"] in positions:
            raise ValueError("Missing title/code or duplicate code")
        if row["employee"]:
            if row["employee"] in employees:
                raise ValueError("Employee is assigned to more than one position")
            employees.add(row["employee"])
        positions[row["code"]] = row
        normalized.append(row)
    for row in normalized:
        visited, parent = {row["code"]}, row["parent"]
        while parent:
            if parent not in positions:
                raise ValueError("Parent position does not exist")
            if parent in visited:
                raise ValueError("Organization cycle is not allowed")
            visited.add(parent)
            parent = positions[parent]["parent"]
    return normalized

